//! The generic manifest interpreter: turns a tool + JSON params into the exact
//! HTTP request the PostHog API expects, reproducing the MCP's request-shaping
//! transforms declaratively. The conformance tests assert byte-for-byte (at the
//! JSON-semantic level) parity with the MCP handlers in
//! `services/mcp/src/tools/generated/*` and `services/mcp/src/api/client.ts`.

use anyhow::{bail, Result};
use serde_json::{json, Map, Value};

use crate::agent::manifest::{Param, Tool};

/// A fully-resolved request, independent of host and HTTP client. Query pairs are
/// kept unencoded and ordered to mirror the MCP's `URLSearchParams` insertion order.
#[derive(Debug, PartialEq, Eq)]
pub struct ResolvedRequest {
    pub method: String,
    pub path: String,
    pub query: Vec<(String, String)>,
    pub body: Option<Value>,
}

impl ResolvedRequest {
    /// JSON preview used by `--dry-run`.
    pub fn to_preview(&self) -> Value {
        let query: Map<String, Value> = self
            .query
            .iter()
            .map(|(k, v)| (k.clone(), Value::String(v.clone())))
            .collect();
        json!({
            "method": self.method,
            "path": self.path,
            "query": Value::Object(query),
            "body": self.body,
        })
    }
}

pub fn build_request(tool: &Tool, params: &Value, project_id: &str) -> Result<ResolvedRequest> {
    let empty = Map::new();
    let params_obj = params.as_object().unwrap_or(&empty);

    if let Some(qw) = &tool.query_wrapper {
        return build_query_wrapper_request(tool, qw, params_obj, project_id);
    }

    let soft_delete_field = tool.soft_delete_field();
    let method = if soft_delete_field.is_some() {
        "PATCH".to_string()
    } else {
        tool.method.clone()
    };

    // Path: substitute {project_id} then each declared path param (cast → stringify → encode).
    let mut path = substitute_project(&tool.path, project_id);
    for p in &tool.params.path {
        let value = match params_obj.get(&p.name) {
            Some(v) if !v.is_null() => apply_cast(p.cast.as_deref(), v.clone()),
            _ => match tool.fallbacks.get(&p.name).map(String::as_str) {
                Some("projectId") => Value::String(project_id.to_string()),
                // Org-scoped resolution isn't wired in the CLI yet (project-scoped default, O5).
                Some("orgId") => bail!(
                    "Parameter '{}' is org-scoped — pass it explicitly (the CLI defaults to project scope)",
                    p.name
                ),
                _ => bail!("Missing required path parameter: {}", p.name),
            },
        };
        path = path.replace(
            &format!("{{{}}}", p.name),
            &encode_uri_component(&scalar_to_string(&value)),
        );
    }

    // Query: apply default when omitted; skip explicit null / empty-array; JSON-stringify objects.
    let mut query = Vec::new();
    for p in &tool.params.query {
        let value = match params_obj.get(&p.name) {
            // Explicit null is a value (not undefined), so the zod default does not apply; it is
            // then dropped during wire serialization.
            Some(Value::Null) => continue,
            Some(v) => v.clone(),
            None => match &p.default {
                Some(d) => d.clone(),
                None => continue,
            },
        };
        if let Value::Array(a) = &value {
            if a.is_empty() {
                continue;
            }
        }
        let value = apply_cast(p.cast.as_deref(), value);
        query.push((wire_name(p), scalar_to_string(&value)));
    }

    // Body: soft-delete override, else whitelist of declared body fields + inject_body.
    let body = if let Some(field) = &soft_delete_field {
        let mut m = Map::new();
        m.insert(field.clone(), Value::Bool(true));
        Some(Value::Object(m))
    } else if !tool.params.body.is_empty() || !tool.inject_body.is_empty() {
        let mut obj = Map::new();
        for p in &tool.params.body {
            // Present (incl. null) → include, mirroring MCP `params[x] !== undefined`. Absent →
            // apply the schema default if any (the MCP zod parse fills it before the handler runs).
            let value = match params_obj.get(&p.name) {
                Some(v) => v.clone(),
                None => match &p.default {
                    Some(d) => d.clone(),
                    None => continue,
                },
            };
            obj.insert(wire_name(p), apply_cast(p.cast.as_deref(), value));
        }
        for (k, v) in &tool.inject_body {
            obj.insert(k.clone(), v.clone());
        }
        Some(Value::Object(obj))
    } else {
        None
    };

    Ok(ResolvedRequest {
        method,
        path,
        query,
        body,
    })
}

fn build_query_wrapper_request(
    tool: &Tool,
    qw: &crate::agent::manifest::QueryWrapper,
    params_obj: &Map<String, Value>,
    project_id: &str,
) -> Result<ResolvedRequest> {
    let path = substitute_project(&tool.path, project_id);

    // `output_format` is a tool-level control, not part of the query body.
    let mut inner = params_obj.clone();
    inner.remove("output_format");
    normalize_filter_group(&mut inner);
    inner.insert("kind".to_string(), Value::String(qw.kind.clone()));

    let query_obj = if let Some(actors) = &qw.actors {
        // Dispatch on the runtime source kind, mirroring client.ts runActorsQuery selection.
        let source_kind = params_obj
            .get("source")
            .and_then(|s| s.get("kind"))
            .and_then(|k| k.as_str())
            .ok_or_else(|| anyhow::anyhow!("Actors query requires `source.kind`"))?;
        let variant = actors
            .source_kind_map
            .get(source_kind)
            .ok_or_else(|| anyhow::anyhow!("Unsupported source kind for actors query: {source_kind}"))?;

        let mut select: Vec<Value> = variant.select.iter().cloned().map(Value::String).collect();
        if let Some(field) = &actors.include_recordings_field {
            if is_truthy(params_obj.get(field)) {
                if let Some(rec) = &actors.recordings_select {
                    select.push(Value::String(rec.clone()));
                }
            }
        }
        let mut wrapped = Map::new();
        wrapped.insert("kind".to_string(), Value::String("ActorsQuery".to_string()));
        wrapped.insert("source".to_string(), Value::Object(inner));
        wrapped.insert("select".to_string(), Value::Array(select));
        wrapped.insert(
            "orderBy".to_string(),
            Value::Array(variant.order_by.iter().cloned().map(Value::String).collect()),
        );
        wrapped.insert("limit".to_string(), json!(variant.limit));
        wrapped
    } else {
        inner
    };

    Ok(ResolvedRequest {
        method: "POST".to_string(),
        path,
        query: vec![],
        body: Some(json!({ "query": Value::Object(query_obj) })),
    })
}

/// Bridge the assistant-facing flat `filterGroup` array to the nested
/// `PropertyGroupFilter` the query API expects (mirrors `normalizeQuery`).
fn normalize_filter_group(query: &mut Map<String, Value>) {
    if let Some(Value::Array(arr)) = query.get("filterGroup").cloned() {
        if arr.is_empty() {
            query.remove("filterGroup");
        } else {
            query.insert(
                "filterGroup".to_string(),
                json!({ "type": "AND", "values": [{ "type": "AND", "values": arr }] }),
            );
        }
    }
}

fn substitute_project(path: &str, project_id: &str) -> String {
    path.replace("{project_id}", &encode_uri_component(project_id))
}

fn wire_name(p: &Param) -> String {
    p.rename.clone().unwrap_or_else(|| p.name.clone())
}

/// `string-int`: convert an all-digits string to a JSON number (mirrors `castStringToInt`).
fn apply_cast(cast: Option<&str>, value: Value) -> Value {
    match cast {
        Some("string-int") => match &value {
            Value::String(s) if is_integer_string(s) => match s.parse::<i64>() {
                Ok(n) => json!(n),
                Err(_) => value,
            },
            _ => value,
        },
        _ => value,
    }
}

fn is_integer_string(s: &str) -> bool {
    let bytes = s.as_bytes();
    let digits = match bytes.first() {
        Some(b'-') => &bytes[1..],
        _ => bytes,
    };
    !digits.is_empty() && digits.iter().all(|b| b.is_ascii_digit())
}

/// `String(v)` for scalars; `JSON.stringify(v)` for objects/arrays (mirrors client.ts query serialization).
fn scalar_to_string(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::Null => "null".to_string(),
        other => serde_json::to_string(other).unwrap_or_default(),
    }
}

/// JS `Boolean(v)` semantics for the actors `includeRecordings` gate.
fn is_truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        Some(Value::String(s)) => !s.is_empty(),
        Some(_) => true,
    }
}

/// JS `encodeURIComponent` semantics (unreserved set differs from RFC 3986 form encoding).
fn encode_uri_component(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        let c = b as char;
        if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '!' | '~' | '*' | '\'' | '(' | ')') {
            out.push(c);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::manifest::load_manifest;

    const PROJECT_ID: &str = "2";

    // Wire-level goldens captured from the REAL MCP handlers by
    // services/mcp/scripts/generate-cli-conformance.ts. Asserting against these makes
    // request parity with the MCP a CI-enforced invariant, not a re-derivation.
    const CONFORMANCE_GOLDENS: &str = include_str!("../../../services/mcp/schema/cli-conformance-goldens.json");

    fn req(tool_name: &str, params: Value) -> ResolvedRequest {
        let manifest = load_manifest().expect("manifest parses");
        let tool = manifest.tools.get(tool_name).expect("tool exists");
        build_request(tool, &params, PROJECT_ID).expect("request builds")
    }

    #[test]
    fn manifest_parses_and_is_nonempty() {
        let manifest = load_manifest().expect("generated manifest parses");
        assert!(manifest.tools.len() > 100, "expected the full generated tool set");
    }

    // Golden expectations are derived from the authoritative MCP source:
    //   services/mcp/src/tools/generated/feature_flags.ts and
    //   services/mcp/src/api/client.ts (request / normalizeQuery / runActorsQuery).

    #[test]
    fn create_feature_flag_builds_post_with_body_whitelist() {
        let r = req(
            "create-feature-flag",
            json!({ "key": "my-flag", "name": "My Flag", "active": true }),
        );
        assert_eq!(r.method, "POST");
        assert_eq!(r.path, "/api/projects/2/feature_flags/");
        assert!(r.query.is_empty());
        assert_eq!(
            r.body,
            Some(json!({ "key": "my-flag", "name": "My Flag", "active": true }))
        );
    }

    #[test]
    fn delete_feature_flag_soft_deletes_via_patch() {
        let r = req("delete-feature-flag", json!({ "id": "123" }));
        assert_eq!(r.method, "PATCH");
        assert_eq!(r.path, "/api/projects/2/feature_flags/123/");
        assert_eq!(r.body, Some(json!({ "deleted": true })));
    }

    #[test]
    fn get_all_builds_query_in_handler_order_with_casts() {
        // Input order is intentionally reversed; output must follow manifest (handler) order.
        let r = req("feature-flag-get-all", json!({ "search": "foo", "limit": "10" }));
        assert_eq!(r.method, "GET");
        assert_eq!(r.path, "/api/projects/2/feature_flags/");
        assert_eq!(
            r.query,
            vec![
                ("limit".to_string(), "10".to_string()),
                ("search".to_string(), "foo".to_string()),
            ]
        );
        assert_eq!(r.body, None);
    }

    #[test]
    fn get_all_skips_empty_array_and_stringifies_nonempty_array() {
        let r = req(
            "feature-flag-get-all",
            json!({ "tags": ["a", "b"], "excluded_properties": [] }),
        );
        // empty array dropped, non-empty array JSON-stringified
        assert_eq!(r.query, vec![("tags".to_string(), r#"["a","b"]"#.to_string())]);
    }

    #[test]
    fn get_definition_substitutes_and_encodes_path_param() {
        let r = req("feature-flag-get-definition", json!({ "id": "456" }));
        assert_eq!(r.method, "GET");
        assert_eq!(r.path, "/api/projects/2/feature_flags/456/");
    }

    #[test]
    fn missing_required_path_param_errors() {
        let manifest = load_manifest().unwrap();
        let tool = manifest.tools.get("feature-flag-get-definition").unwrap();
        let err = build_request(tool, &json!({}), PROJECT_ID).unwrap_err();
        assert!(err.to_string().contains("Missing required path parameter: id"));
    }

    #[test]
    fn update_feature_flag_splits_path_and_body() {
        let r = req(
            "update-feature-flag",
            json!({ "id": "123", "name": "New", "active": false }),
        );
        assert_eq!(r.method, "PATCH");
        assert_eq!(r.path, "/api/projects/2/feature_flags/123/");
        assert_eq!(r.body, Some(json!({ "name": "New", "active": false })));
    }

    #[test]
    fn query_trends_wraps_strips_output_format_and_nests_filter_group() {
        let r = req(
            "query-trends",
            json!({
                "series": [{ "kind": "EventsNode", "event": "$pageview" }],
                "filterGroup": [{ "k": 1 }],
                "output_format": "json"
            }),
        );
        assert_eq!(r.method, "POST");
        assert_eq!(r.path, "/api/environments/2/query/");
        assert_eq!(
            r.body,
            Some(json!({
                "query": {
                    "series": [{ "kind": "EventsNode", "event": "$pageview" }],
                    "filterGroup": { "type": "AND", "values": [{ "type": "AND", "values": [{ "k": 1 }] }] },
                    "kind": "TrendsQuery"
                }
            }))
        );
    }

    #[test]
    fn query_trends_actors_rewraps_into_actors_query_with_recordings() {
        let r = req(
            "query-trends-actors",
            json!({
                "source": { "kind": "TrendsQuery", "series": [] },
                "includeRecordings": true,
                "filterGroup": []
            }),
        );
        assert_eq!(r.method, "POST");
        assert_eq!(r.path, "/api/environments/2/query/");
        assert_eq!(
            r.body,
            Some(json!({
                "query": {
                    "kind": "ActorsQuery",
                    "source": {
                        "source": { "kind": "TrendsQuery", "series": [] },
                        "includeRecordings": true,
                        "kind": "InsightActorsQuery"
                    },
                    "select": ["actor", "event_count", "matched_recordings"],
                    "orderBy": ["event_count DESC", "actor_id DESC"],
                    "limit": 100
                }
            }))
        );
    }

    #[test]
    fn query_trends_actors_omits_recordings_when_not_requested() {
        let r = req("query-trends-actors", json!({ "source": { "kind": "TrendsQuery" } }));
        let select = &r.body.unwrap()["query"]["select"];
        assert_eq!(select, &json!(["actor", "event_count"]));
    }

    #[test]
    fn query_lifecycle_actors_uses_lifecycle_variant() {
        // Same tool family, different source.kind → different select/orderBy (mirrors client.ts).
        let r = req("query-lifecycle-actors", json!({ "source": { "kind": "LifecycleQuery" } }));
        let query = &r.body.unwrap()["query"];
        assert_eq!(query["select"], json!(["actor"]));
        assert_eq!(query["orderBy"], json!([]));
        assert_eq!(query["kind"], json!("ActorsQuery"));
    }

    #[test]
    fn actors_unsupported_source_kind_errors() {
        let manifest = load_manifest().unwrap();
        let tool = manifest.tools.get("query-trends-actors").unwrap();
        let err = build_request(tool, &json!({ "source": { "kind": "PathsQuery" } }), PROJECT_ID).unwrap_err();
        assert!(err.to_string().contains("Unsupported source kind"));
    }

    #[test]
    fn persons_property_delete_applies_rename() {
        // rename_params: agent passes `unset`, the wire sends `$unset`.
        let r = req("persons-property-delete", json!({ "id": "abc", "unset": ["email"] }));
        assert_eq!(r.method, "POST");
        assert_eq!(r.path, "/api/projects/2/persons/abc/delete_property/");
        assert_eq!(r.body, Some(json!({ "$unset": ["email"] })));
    }

    #[test]
    fn external_data_sources_create_injects_body_and_applies_default() {
        let r = req("external-data-sources-create", json!({ "source_type": "Stripe" }));
        let body = r.body.unwrap();
        assert_eq!(body["source_type"], json!("Stripe"));
        assert_eq!(body["created_via"], json!("mcp")); // inject_body
        assert_eq!(body["access_method"], json!("warehouse")); // OpenAPI body default applied
    }

    #[test]
    fn activity_log_list_does_not_apply_param_override_default() {
        // page_size has a param_overrides default of 10, but it is `.default(10).optional()` —
        // zod's optional short-circuits omitted input, so the MCP omits it and so must we.
        let r = req("activity-log-list", json!({}));
        assert!(
            !r.query.iter().any(|(k, _)| k == "page_size"),
            "page_size must not be sent when omitted"
        );
    }

    #[test]
    fn live_conformance_against_mcp_goldens() {
        let goldens: serde_json::Map<String, Value> =
            serde_json::from_str(CONFORMANCE_GOLDENS).expect("goldens parse");
        let manifest = load_manifest().unwrap();
        assert!(goldens.len() >= 5, "expected a meaningful conformance corpus");

        for (name, entry) in &goldens {
            let params = &entry["params"];
            let expected = &entry["request"];
            let tool = manifest
                .tools
                .get(name)
                .unwrap_or_else(|| panic!("golden tool {name} missing from manifest"));
            let r = build_request(tool, params, PROJECT_ID).unwrap_or_else(|e| panic!("{name}: {e}"));

            assert_eq!(r.method, expected["method"].as_str().unwrap(), "method mismatch for {name}");
            assert_eq!(r.path, expected["path"].as_str().unwrap(), "path mismatch for {name}");
            let r_query: serde_json::Map<String, Value> = r
                .query
                .iter()
                .map(|(k, v)| (k.clone(), Value::String(v.clone())))
                .collect();
            assert_eq!(Value::Object(r_query), expected["query"], "query mismatch for {name}");
            let r_body = r.body.clone().unwrap_or(Value::Null);
            assert_eq!(r_body, expected["body"], "body mismatch for {name}");
        }
    }
}
