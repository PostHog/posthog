//! Uncompressed message-size comparison of JSON, Protobuf and Avro for the
//! `ClickHouseEvent` schema (see `nodejs/src/types.ts`).
//!
//! Events carry several "moderately large" property maps (`properties`,
//! `person_properties`, `group{0..4}_properties`). In typed wire formats those
//! maps can be modelled two ways, both of which we measure:
//!   * `*-map`   — a native `map<string,string>` (values stringified)
//!   * `*-bytes` — the canonical JSON of the map stored in a single `bytes` field
//!
//! We synthesise 10k events whose payloads span ~500 B to ~400 KB and report the
//! uncompressed serialized size of every event under each encoding.

use std::collections::HashMap;

use apache_avro::{types::Value as AvroValue, Schema};
use prost::Message;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde_json::{json, Map as JsonMap, Value as JsonValue};

const NUM_EVENTS: usize = 10_000;
const MIN_TARGET_BYTES: f64 = 500.0;
const MAX_TARGET_BYTES: f64 = 400_000.0;

// ---------------------------------------------------------------------------
// In-memory event model (format-agnostic source of truth for every encoder).
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
enum PersonMode {
    Full = 0,
    Propertyless = 1,
    ForceUpgrade = 2,
}

impl PersonMode {
    fn as_str(self) -> &'static str {
        match self {
            PersonMode::Full => "full",
            PersonMode::Propertyless => "propertyless",
            PersonMode::ForceUpgrade => "force_upgrade",
        }
    }
    fn avro_index(self) -> u32 {
        self as i32 as u32
    }
}

#[derive(Clone)]
struct Element {
    text: String,
    tag_name: String,
    href: String,
    attr_id: String,
    attr_class: Vec<String>,
    nth_child: i32,
    nth_of_type: i32,
    attributes: JsonMap<String, JsonValue>,
}

/// A property bag preserved as ordered JSON so every encoder sees identical data.
type PropertyMap = JsonMap<String, JsonValue>;

struct Event {
    uuid: String,
    event: String,
    team_id: i64,
    project_id: i64,
    distinct_id: String,
    person_id: String,
    timestamp_ms: i64,
    created_at_ms: i64,
    person_created_at_ms: i64,
    person_mode: PersonMode,
    properties: PropertyMap,
    person_properties: PropertyMap,
    group_properties: [PropertyMap; 5],
    elements_chain: Vec<Element>,
}

// ---------------------------------------------------------------------------
// Synthetic data generation.
// ---------------------------------------------------------------------------

fn rand_string(rng: &mut StdRng, len: usize) -> String {
    const CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.";
    (0..len).map(|_| CHARS[rng.gen_range(0..CHARS.len())] as char).collect()
}

// Realistic, repetitive value tokens so compression behaves like production event
// data (URLs, UAs, enum-ish values) rather than incompressible random noise.
const VALUE_CORPUS: &[&str] = &[
    "https://app.posthog.com/project/2/insights",
    "https://example.com/pricing",
    "https://example.com/blog/how-to-use-feature-flags",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "AppleWebKit/537.36 (KHTML, like Gecko)",
    "Chrome/120.0.0.0 Safari/537.36",
    "Mac OS X", "Windows", "Linux", "iOS", "Android",
    "Chrome", "Firefox", "Safari", "Edge",
    "en-US", "en-GB", "de-DE", "fr-FR", "pt-BR",
    "United States", "Germany", "United Kingdom", "France", "Brazil",
    "California", "Berlin", "London", "Paris", "Sao Paulo",
    "desktop", "mobile", "tablet",
    "true", "false", "null",
    "organic", "direct", "referral", "paid",
    "google.com", "facebook.com", "twitter.com", "linkedin.com",
    "newsletter", "summer_sale", "product_hunt",
    "checkout", "dashboard", "settings", "pricing", "signup", "login",
    "button", "submit", "link", "form",
    "enabled", "disabled", "control", "test", "variant_a", "variant_b",
    "free", "pro", "enterprise", "scale",
    "admin", "member", "viewer", "owner",
    "2024-01-15T10:30:00.000Z", "2024-03-22T08:14:59.123Z",
    "session_abc123def456", "user_xyz789ghi012",
    "1920", "1080", "390", "844", "120.0.0.0",
];

// Realistic, frequently-reused property key names (drives cross-event redundancy).
const KEY_POOL: &[&str] = &[
    "$current_url", "$host", "$pathname", "$browser", "$browser_version",
    "$os", "$os_version", "$device_type", "$screen_height", "$screen_width",
    "$viewport_height", "$viewport_width", "$lib", "$lib_version", "$referrer",
    "$referring_domain", "$session_id", "$window_id", "$ip", "$geoip_country_code",
    "$geoip_city_name", "$geoip_subdivision_1_name", "utm_source", "utm_medium",
    "utm_campaign", "utm_term", "utm_content", "$active_feature_flags", "$insert_id",
    "title", "plan", "role", "is_admin", "experiment_variant", "button_text",
    "element_type", "page_category", "search_query", "items_count", "total_price",
    "currency", "logged_in", "ab_test_group", "app_version", "build_number",
    "locale", "timezone", "connection_type", "feature_flag_response", "cohort",
];

/// A string built from corpus tokens, so content repeats within and across events.
fn corpus_string(rng: &mut StdRng, len: usize) -> String {
    let seps = ["/", " ", "-", ".", "_", "?", "&"];
    let mut s = String::with_capacity(len + 16);
    while s.len() < len {
        if !s.is_empty() {
            s.push_str(seps[rng.gen_range(0..seps.len())]);
        }
        s.push_str(VALUE_CORPUS[rng.gen_range(0..VALUE_CORPUS.len())]);
    }
    s.truncate(len); // tokens are ASCII, so this is a valid char boundary
    s
}

/// A realistically-typed property value (string / number / bool / small nested).
fn rand_value(rng: &mut StdRng, value_len: usize) -> JsonValue {
    match rng.gen_range(0..100) {
        0..=69 => JsonValue::String(corpus_string(rng, value_len.max(4))),
        70..=84 => json!(rng.gen_range(-1_000_000..1_000_000)),
        85..=92 => json!(rng.gen_range(-1000.0..1000.0)),
        93..=96 => JsonValue::Bool(rng.gen_bool(0.5)),
        _ => json!({
            "x": corpus_string(rng, (value_len / 2).max(4)),
            "y": rng.gen_range(0..1000),
            "z": [rng.gen_range(0..10), rng.gen_range(0..10)],
        }),
    }
}

/// Property key name, reusing the pool first (so common keys recur across events).
fn key_for(prefix: &str, i: usize) -> String {
    let base = KEY_POOL[i % KEY_POOL.len()];
    if i < KEY_POOL.len() {
        format!("{prefix}{base}")
    } else {
        format!("{prefix}{base}_{i}")
    }
}

/// Approximate the JSON byte cost of a key/value pair (key + value + punctuation).
fn approx_pair_bytes(key: &str, value: &JsonValue) -> usize {
    // `"key":<value>,` — quotes, colon, comma.
    key.len() + 4 + serde_json::to_string(value).map(|s| s.len()).unwrap_or(8)
}

/// Fill a property map until its estimated JSON size reaches `budget` bytes.
fn build_property_map(rng: &mut StdRng, prefix: &str, budget: usize, value_len: usize) -> PropertyMap {
    let mut map = JsonMap::new();
    let mut size = 2; // surrounding braces
    let mut i = 0usize;
    while size < budget {
        let key = key_for(prefix, i);
        let value = rand_value(rng, value_len);
        size += approx_pair_bytes(&key, &value);
        map.insert(key, value);
        i += 1;
    }
    map
}

fn build_elements(rng: &mut StdRng, count: usize) -> Vec<Element> {
    (0..count)
        .map(|_| {
            let mut attributes = JsonMap::new();
            for j in 0..rng.gen_range(0..4) {
                attributes.insert(format!("data-attr-{j}"), JsonValue::String(rand_string(rng, 12)));
            }
            let text_len = rng.gen_range(0..20);
            let href_len = rng.gen_range(0..30);
            let tag_idx = rng.gen_range(0..5);
            let class_count = rng.gen_range(0..3);
            Element {
                text: rand_string(rng, text_len),
                tag_name: ["div", "span", "a", "button", "input"][tag_idx].to_string(),
                href: rand_string(rng, href_len),
                attr_id: rand_string(rng, 8),
                attr_class: (0..class_count).map(|_| rand_string(rng, 8)).collect(),
                nth_child: rng.gen_range(0..20),
                nth_of_type: rng.gen_range(0..20),
                attributes,
            }
        })
        .collect()
}

fn generate_event(rng: &mut StdRng, target_bytes: usize) -> Event {
    // Scale value width with target so huge events don't need absurd key counts.
    let value_len = (target_bytes / 400).clamp(20, 400);

    // Small fixed-ish extras; most of the budget goes into `properties`.
    let (person_budget, group0_budget, group1_budget, elements) = if target_bytes < 2_000 {
        (120usize, 0usize, 0usize, build_elements(rng, 1))
    } else {
        (600usize, 400usize, 200usize, build_elements(rng, 3))
    };

    let person_properties = build_property_map(rng, "person_prop", person_budget, 40);
    let mut group_properties: [PropertyMap; 5] = Default::default();
    group_properties[0] = build_property_map(rng, "group0_prop", group0_budget, 30);
    group_properties[1] = build_property_map(rng, "group1_prop", group1_budget, 30);

    // Remaining budget after the (roughly known) baseline goes to `properties`.
    let baseline = 350 + person_budget + group0_budget + group1_budget;
    let prop_budget = target_bytes.saturating_sub(baseline).max(0);
    let properties = build_property_map(rng, "prop", prop_budget, value_len);

    Event {
        uuid: format!("{:08x}-0000-4000-8000-{:012x}", rng.gen::<u32>(), rng.gen::<u64>() & 0xffff_ffff_ffff),
        event: ["$pageview", "$autocapture", "$identify", "custom_event", "$pageleave"]
            [rng.gen_range(0..5)]
            .to_string(),
        team_id: rng.gen_range(1..100_000),
        project_id: rng.gen_range(1..100_000),
        distinct_id: rand_string(rng, 24),
        person_id: format!("{:08x}-0000-4000-8000-{:012x}", rng.gen::<u32>(), rng.gen::<u64>() & 0xffff_ffff_ffff),
        timestamp_ms: 1_700_000_000_000 + rng.gen_range(0..1_000_000_000),
        created_at_ms: 1_700_000_000_000 + rng.gen_range(0..1_000_000_000),
        person_created_at_ms: 1_600_000_000_000 + rng.gen_range(0..1_000_000_000),
        person_mode: match rng.gen_range(0..3) {
            0 => PersonMode::Full,
            1 => PersonMode::Propertyless,
            _ => PersonMode::ForceUpgrade,
        },
        properties,
        person_properties,
        group_properties,
        elements_chain: elements,
    }
}

// ---------------------------------------------------------------------------
// JSON encoding (properties stay native JSON objects — the baseline).
// ---------------------------------------------------------------------------

fn element_to_json(e: &Element) -> JsonValue {
    json!({
        "text": e.text,
        "tag_name": e.tag_name,
        "href": e.href,
        "attr_id": e.attr_id,
        "attr_class": e.attr_class,
        "nth_child": e.nth_child,
        "nth_of_type": e.nth_of_type,
        "attributes": e.attributes,
    })
}

fn event_to_json_value(e: &Event) -> JsonValue {
    json!({
        "uuid": e.uuid,
        "event": e.event,
        "team_id": e.team_id,
        "project_id": e.project_id,
        "distinct_id": e.distinct_id,
        "person_id": e.person_id,
        "timestamp": e.timestamp_ms,
        "created_at": e.created_at_ms,
        "person_created_at": e.person_created_at_ms,
        "person_mode": e.person_mode.as_str(),
        "properties": e.properties,
        "person_properties": e.person_properties,
        "group0_properties": e.group_properties[0],
        "group1_properties": e.group_properties[1],
        "group2_properties": e.group_properties[2],
        "group3_properties": e.group_properties[3],
        "group4_properties": e.group_properties[4],
        "elements_chain": e.elements_chain.iter().map(element_to_json).collect::<Vec<_>>(),
    })
}

fn json_bytes(e: &Event) -> Vec<u8> {
    serde_json::to_vec(&event_to_json_value(e)).expect("json serialize")
}

/// MessagePack is schemaless binary — same dynamic shape as JSON, no shared
/// schema/registry needed. We encode the identical JSON value for fairness.
fn msgpack_bytes(e: &Event) -> Vec<u8> {
    rmp_serde::to_vec(&event_to_json_value(e)).expect("msgpack serialize")
}

// ---------------------------------------------------------------------------
// Shared helper: stringify a property map for the "native map" representations.
// ---------------------------------------------------------------------------

fn stringify_map(m: &PropertyMap) -> HashMap<String, String> {
    m.iter()
        .map(|(k, v)| {
            let s = match v {
                JsonValue::String(s) => s.clone(),
                other => other.to_string(),
            };
            (k.clone(), s)
        })
        .collect()
}

fn map_to_json_bytes(m: &PropertyMap) -> Vec<u8> {
    serde_json::to_vec(m).expect("json serialize map")
}

// ---------------------------------------------------------------------------
// Protobuf encoding (prost derive — no .proto / protoc needed).
// ---------------------------------------------------------------------------

#[derive(Clone, PartialEq, Message)]
struct PbElement {
    #[prost(string, tag = "1")]
    text: String,
    #[prost(string, tag = "2")]
    tag_name: String,
    #[prost(string, tag = "3")]
    href: String,
    #[prost(string, tag = "4")]
    attr_id: String,
    #[prost(string, repeated, tag = "5")]
    attr_class: Vec<String>,
    #[prost(int32, tag = "6")]
    nth_child: i32,
    #[prost(int32, tag = "7")]
    nth_of_type: i32,
    #[prost(map = "string, string", tag = "8")]
    attributes: HashMap<String, String>,
}

#[derive(Clone, PartialEq, Message)]
struct PbScalars {
    #[prost(string, tag = "1")]
    uuid: String,
    #[prost(string, tag = "2")]
    event: String,
    #[prost(int64, tag = "3")]
    team_id: i64,
    #[prost(int64, tag = "4")]
    project_id: i64,
    #[prost(string, tag = "5")]
    distinct_id: String,
    #[prost(string, tag = "6")]
    person_id: String,
    #[prost(int64, tag = "7")]
    timestamp_ms: i64,
    #[prost(int64, tag = "8")]
    created_at_ms: i64,
    #[prost(int64, tag = "9")]
    person_created_at_ms: i64,
    #[prost(int32, tag = "10")]
    person_mode: i32,
    #[prost(message, repeated, tag = "20")]
    elements_chain: Vec<PbElement>,
}

/// Properties modelled as native `map<string,string>` fields.
#[derive(Clone, PartialEq, Message)]
struct PbEventMap {
    #[prost(message, tag = "1")]
    scalars: Option<PbScalars>,
    #[prost(map = "string, string", tag = "11")]
    properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "12")]
    person_properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "13")]
    group0_properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "14")]
    group1_properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "15")]
    group2_properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "16")]
    group3_properties: HashMap<String, String>,
    #[prost(map = "string, string", tag = "17")]
    group4_properties: HashMap<String, String>,
}

/// Properties modelled as opaque JSON `bytes` fields.
#[derive(Clone, PartialEq, Message)]
struct PbEventBytes {
    #[prost(message, tag = "1")]
    scalars: Option<PbScalars>,
    #[prost(bytes = "vec", tag = "11")]
    properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "12")]
    person_properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "13")]
    group0_properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "14")]
    group1_properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "15")]
    group2_properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "16")]
    group3_properties: Vec<u8>,
    #[prost(bytes = "vec", tag = "17")]
    group4_properties: Vec<u8>,
}

fn pb_scalars(e: &Event) -> PbScalars {
    PbScalars {
        uuid: e.uuid.clone(),
        event: e.event.clone(),
        team_id: e.team_id,
        project_id: e.project_id,
        distinct_id: e.distinct_id.clone(),
        person_id: e.person_id.clone(),
        timestamp_ms: e.timestamp_ms,
        created_at_ms: e.created_at_ms,
        person_created_at_ms: e.person_created_at_ms,
        person_mode: e.person_mode as i32,
        elements_chain: e
            .elements_chain
            .iter()
            .map(|el| PbElement {
                text: el.text.clone(),
                tag_name: el.tag_name.clone(),
                href: el.href.clone(),
                attr_id: el.attr_id.clone(),
                attr_class: el.attr_class.clone(),
                nth_child: el.nth_child,
                nth_of_type: el.nth_of_type,
                attributes: el
                    .attributes
                    .iter()
                    .map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string()))
                    .collect(),
            })
            .collect(),
    }
}

fn pb_event_map(e: &Event) -> PbEventMap {
    PbEventMap {
        scalars: Some(pb_scalars(e)),
        properties: stringify_map(&e.properties),
        person_properties: stringify_map(&e.person_properties),
        group0_properties: stringify_map(&e.group_properties[0]),
        group1_properties: stringify_map(&e.group_properties[1]),
        group2_properties: stringify_map(&e.group_properties[2]),
        group3_properties: stringify_map(&e.group_properties[3]),
        group4_properties: stringify_map(&e.group_properties[4]),
    }
}

fn pb_event_bytes(e: &Event) -> PbEventBytes {
    PbEventBytes {
        scalars: Some(pb_scalars(e)),
        properties: map_to_json_bytes(&e.properties),
        person_properties: map_to_json_bytes(&e.person_properties),
        group0_properties: map_to_json_bytes(&e.group_properties[0]),
        group1_properties: map_to_json_bytes(&e.group_properties[1]),
        group2_properties: map_to_json_bytes(&e.group_properties[2]),
        group3_properties: map_to_json_bytes(&e.group_properties[3]),
        group4_properties: map_to_json_bytes(&e.group_properties[4]),
    }
}

fn protobuf_map_size(e: &Event) -> usize {
    pb_event_map(e).encoded_len()
}

fn protobuf_bytes_size(e: &Event) -> usize {
    pb_event_bytes(e).encoded_len()
}

fn protobuf_bytes_encode(e: &Event) -> Vec<u8> {
    pb_event_bytes(e).encode_to_vec()
}

// ---------------------------------------------------------------------------
// Avro encoding (raw datum — no container/object header).
// ---------------------------------------------------------------------------

fn avro_map_schema() -> Schema {
    Schema::parse_str(&avro_map_schema_json()).expect("valid avro map schema")
}

fn avro_bytes_schema() -> Schema {
    Schema::parse_str(&avro_bytes_schema_json()).expect("valid avro bytes schema")
}

fn avro_element_value(e: &Element) -> AvroValue {
    AvroValue::Record(vec![
        ("text".into(), AvroValue::String(e.text.clone())),
        ("tag_name".into(), AvroValue::String(e.tag_name.clone())),
        ("href".into(), AvroValue::String(e.href.clone())),
        ("attr_id".into(), AvroValue::String(e.attr_id.clone())),
        (
            "attr_class".into(),
            AvroValue::Array(e.attr_class.iter().cloned().map(AvroValue::String).collect()),
        ),
        ("nth_child".into(), AvroValue::Int(e.nth_child)),
        ("nth_of_type".into(), AvroValue::Int(e.nth_of_type)),
        (
            "attributes".into(),
            AvroValue::Map(
                e.attributes
                    .iter()
                    .map(|(k, v)| (k.clone(), AvroValue::String(v.as_str().unwrap_or_default().to_string())))
                    .collect(),
            ),
        ),
    ])
}

fn avro_scalar_fields(e: &Event) -> Vec<(String, AvroValue)> {
    vec![
        ("uuid".into(), AvroValue::String(e.uuid.clone())),
        ("event".into(), AvroValue::String(e.event.clone())),
        ("team_id".into(), AvroValue::Long(e.team_id)),
        ("project_id".into(), AvroValue::Long(e.project_id)),
        ("distinct_id".into(), AvroValue::String(e.distinct_id.clone())),
        ("person_id".into(), AvroValue::String(e.person_id.clone())),
        ("timestamp".into(), AvroValue::Long(e.timestamp_ms)),
        ("created_at".into(), AvroValue::Long(e.created_at_ms)),
        ("person_created_at".into(), AvroValue::Long(e.person_created_at_ms)),
        (
            "person_mode".into(),
            AvroValue::Enum(e.person_mode.avro_index(), e.person_mode.as_str().to_string()),
        ),
        (
            "elements_chain".into(),
            AvroValue::Array(e.elements_chain.iter().map(avro_element_value).collect()),
        ),
    ]
}

fn avro_map_value(m: &PropertyMap) -> AvroValue {
    AvroValue::Map(
        m.iter()
            .map(|(k, v)| {
                let s = match v {
                    JsonValue::String(s) => s.clone(),
                    other => other.to_string(),
                };
                (k.clone(), AvroValue::String(s))
            })
            .collect(),
    )
}

fn avro_map_record(e: &Event) -> AvroValue {
    let mut fields = avro_scalar_fields(e);
    fields.push(("properties".into(), avro_map_value(&e.properties)));
    fields.push(("person_properties".into(), avro_map_value(&e.person_properties)));
    for i in 0..5 {
        fields.push((format!("group{i}_properties"), avro_map_value(&e.group_properties[i])));
    }
    AvroValue::Record(fields)
}

fn avro_bytes_record(e: &Event) -> AvroValue {
    let mut fields = avro_scalar_fields(e);
    fields.push(("properties".into(), AvroValue::Bytes(map_to_json_bytes(&e.properties))));
    fields.push((
        "person_properties".into(),
        AvroValue::Bytes(map_to_json_bytes(&e.person_properties)),
    ));
    for i in 0..5 {
        fields.push((
            format!("group{i}_properties"),
            AvroValue::Bytes(map_to_json_bytes(&e.group_properties[i])),
        ));
    }
    AvroValue::Record(fields)
}

fn avro_map_size(e: &Event, schema: &Schema) -> usize {
    apache_avro::to_avro_datum(schema, avro_map_record(e)).expect("avro map datum").len()
}

fn avro_bytes_size(e: &Event, schema: &Schema) -> usize {
    apache_avro::to_avro_datum(schema, avro_bytes_record(e)).expect("avro bytes datum").len()
}

fn avro_bytes_encode(e: &Event, schema: &Schema) -> Vec<u8> {
    apache_avro::to_avro_datum(schema, avro_bytes_record(e)).expect("avro bytes datum")
}

// Avro schemas. Field order MUST match the Value::Record field order above.
const AVRO_COMMON_FIELDS: &str = r#"
    {"name":"uuid","type":"string"},
    {"name":"event","type":"string"},
    {"name":"team_id","type":"long"},
    {"name":"project_id","type":"long"},
    {"name":"distinct_id","type":"string"},
    {"name":"person_id","type":"string"},
    {"name":"timestamp","type":"long"},
    {"name":"created_at","type":"long"},
    {"name":"person_created_at","type":"long"},
    {"name":"person_mode","type":{"type":"enum","name":"PersonMode","symbols":["full","propertyless","force_upgrade"]}},
    {"name":"elements_chain","type":{"type":"array","items":{
        "type":"record","name":"Element","fields":[
            {"name":"text","type":"string"},
            {"name":"tag_name","type":"string"},
            {"name":"href","type":"string"},
            {"name":"attr_id","type":"string"},
            {"name":"attr_class","type":{"type":"array","items":"string"}},
            {"name":"nth_child","type":"int"},
            {"name":"nth_of_type","type":"int"},
            {"name":"attributes","type":{"type":"map","values":"string"}}
        ]}}}
"#;

fn avro_map_schema_json() -> String {
    format!(
        r#"{{"type":"record","name":"ClickHouseEvent","fields":[{common},
            {{"name":"properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"person_properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"group0_properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"group1_properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"group2_properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"group3_properties","type":{{"type":"map","values":"string"}}}},
            {{"name":"group4_properties","type":{{"type":"map","values":"string"}}}}
        ]}}"#,
        common = AVRO_COMMON_FIELDS
    )
}

fn avro_bytes_schema_json() -> String {
    format!(
        r#"{{"type":"record","name":"ClickHouseEvent","fields":[{common},
            {{"name":"properties","type":"bytes"}},
            {{"name":"person_properties","type":"bytes"}},
            {{"name":"group0_properties","type":"bytes"}},
            {{"name":"group1_properties","type":"bytes"}},
            {{"name":"group2_properties","type":"bytes"}},
            {{"name":"group3_properties","type":"bytes"}},
            {{"name":"group4_properties","type":"bytes"}}
        ]}}"#,
        common = AVRO_COMMON_FIELDS
    )
}

// ---------------------------------------------------------------------------
// Stats + reporting.
// ---------------------------------------------------------------------------

struct Stats {
    name: &'static str,
    sizes: Vec<usize>,
}

impl Stats {
    fn total(&self) -> u64 {
        self.sizes.iter().map(|&s| s as u64).sum()
    }
    fn mean(&self) -> f64 {
        self.total() as f64 / self.sizes.len() as f64
    }
    fn percentile(&self, sorted: &[usize], p: f64) -> usize {
        if sorted.is_empty() {
            return 0;
        }
        let idx = ((p / 100.0) * (sorted.len() as f64 - 1.0)).round() as usize;
        sorted[idx.min(sorted.len() - 1)]
    }
}

fn human(bytes: f64) -> String {
    if bytes >= 1_048_576.0 {
        format!("{:.2} MiB", bytes / 1_048_576.0)
    } else if bytes >= 1024.0 {
        format!("{:.2} KiB", bytes / 1024.0)
    } else {
        format!("{bytes:.0} B")
    }
}

// ---------------------------------------------------------------------------
// Compression codecs + benchmark runner.
// ---------------------------------------------------------------------------

use std::io::{Read, Write};
use std::time::Instant;

struct CompResult {
    name: String,
    total_in: u64,
    total_out: u64,
    sorted_ratios: Vec<f64>,
    comp_secs: f64,
    decomp_secs: f64,
}

impl CompResult {
    fn overall_ratio(&self) -> f64 {
        self.total_in as f64 / self.total_out as f64
    }
    fn p50_ratio(&self) -> f64 {
        self.sorted_ratios[self.sorted_ratios.len() / 2]
    }
    fn comp_mbps(&self) -> f64 {
        self.total_in as f64 / self.comp_secs / 1e6
    }
    fn decomp_mbps(&self) -> f64 {
        self.total_in as f64 / self.decomp_secs / 1e6
    }
}

/// Compress + decompress every payload, timing each direction over the whole set.
fn run_codec<C, D>(name: &str, payloads: &[Vec<u8>], compress: C, decompress: D) -> CompResult
where
    C: Fn(&[u8]) -> Vec<u8>,
    D: Fn(&[u8]) -> Vec<u8>,
{
    let mut compressed: Vec<Vec<u8>> = Vec::with_capacity(payloads.len());
    let t0 = Instant::now();
    for p in payloads {
        compressed.push(compress(p));
    }
    let comp_secs = t0.elapsed().as_secs_f64();

    let total_in: u64 = payloads.iter().map(|p| p.len() as u64).sum();
    let total_out: u64 = compressed.iter().map(|c| c.len() as u64).sum();
    let mut sorted_ratios: Vec<f64> = payloads
        .iter()
        .zip(&compressed)
        .map(|(p, c)| p.len() as f64 / c.len().max(1) as f64)
        .collect();
    sorted_ratios.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let t1 = Instant::now();
    let mut check: u64 = 0;
    for (c, p) in compressed.iter().zip(payloads) {
        let out = decompress(c);
        assert_eq!(out.len(), p.len(), "{name} round-trip length mismatch");
        check = check.wrapping_add(out.len() as u64);
    }
    let decomp_secs = t1.elapsed().as_secs_f64();
    assert!(check > 0);

    CompResult { name: name.to_string(), total_in, total_out, sorted_ratios, comp_secs, decomp_secs }
}

fn gzip_compress(d: &[u8]) -> Vec<u8> {
    let mut e = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::new(6));
    e.write_all(d).unwrap();
    e.finish().unwrap()
}
fn gzip_decompress(d: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    flate2::read::GzDecoder::new(d).read_to_end(&mut out).unwrap();
    out
}
fn brotli_compress(d: &[u8], quality: u32) -> Vec<u8> {
    let mut out = Vec::new();
    {
        let mut w = brotli::CompressorWriter::new(&mut out, 4096, quality, 22);
        w.write_all(d).unwrap();
    }
    out
}
fn brotli_decompress(d: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    brotli::Decompressor::new(d, 4096).read_to_end(&mut out).unwrap();
    out
}

/// Run the standard codec line-up against one base encoding's payloads.
fn run_all_codecs(payloads: &[Vec<u8>]) -> Vec<CompResult> {
    vec![
        run_codec(
            "lz4",
            payloads,
            |d| lz4_flex::compress_prepend_size(d),
            |d| lz4_flex::decompress_size_prepended(d).unwrap(),
        ),
        run_codec(
            "snappy",
            payloads,
            |d| snap::raw::Encoder::new().compress_vec(d).unwrap(),
            |d| snap::raw::Decoder::new().decompress_vec(d).unwrap(),
        ),
        run_codec("gzip-6", payloads, gzip_compress, gzip_decompress),
        run_codec("zstd-1", payloads, |d| zstd::stream::encode_all(d, 1).unwrap(), |d| zstd::stream::decode_all(d).unwrap()),
        run_codec("zstd-3", payloads, |d| zstd::stream::encode_all(d, 3).unwrap(), |d| zstd::stream::decode_all(d).unwrap()),
        run_codec("zstd-9", payloads, |d| zstd::stream::encode_all(d, 9).unwrap(), |d| zstd::stream::decode_all(d).unwrap()),
        run_codec("brotli-5", payloads, |d| brotli_compress(d, 5), brotli_decompress),
    ]
}

fn print_comp_table(title: &str, total_in: f64, results: &[CompResult]) {
    println!("\n{title}");
    println!("  (uncompressed total: {})", human(total_in));
    println!(
        "{:<12} {:>12} {:>10} {:>10} {:>12} {:>13} {:>9}",
        "codec", "total", "ratio", "p50 ratio", "comp MB/s", "decomp MB/s", "vs none"
    );
    println!("{}", "-".repeat(82));
    for r in results {
        println!(
            "{:<12} {:>12} {:>9.2}x {:>9.2}x {:>12.0} {:>13.0} {:>8.1}%",
            r.name,
            human(r.total_out as f64),
            r.overall_ratio(),
            r.p50_ratio(),
            r.comp_mbps(),
            r.decomp_mbps(),
            r.total_out as f64 / total_in * 100.0,
        );
    }
}

/// Concatenate payloads into ~`batch_bytes` chunks (proxy for Kafka batch compression).
fn batch_payloads(payloads: &[Vec<u8>], batch_bytes: usize) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let mut cur: Vec<u8> = Vec::new();
    for p in payloads {
        if !cur.is_empty() && cur.len() + p.len() > batch_bytes {
            out.push(std::mem::take(&mut cur));
        }
        cur.extend_from_slice(p);
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn main() {
    println!("Generating {NUM_EVENTS} synthetic ClickHouseEvent payloads (~500 B .. ~400 KB)...\n");

    let mut rng = StdRng::seed_from_u64(0xC0FFEE);

    // Log-uniform target sizes so both tiny and huge events are well represented.
    let log_min = MIN_TARGET_BYTES.ln();
    let log_max = MAX_TARGET_BYTES.ln();

    let mut events = Vec::with_capacity(NUM_EVENTS);
    for _ in 0..NUM_EVENTS {
        let t: f64 = rng.gen_range(0.0..1.0);
        let target = (log_min + t * (log_max - log_min)).exp() as usize;
        events.push(generate_event(&mut rng, target));
    }

    let avro_map_s = avro_map_schema();
    let avro_bytes_s = avro_bytes_schema();

    // Materialise the two schemaless payloads once — reused for compression.
    let json_payloads: Vec<Vec<u8>> = events.iter().map(json_bytes).collect();
    let msgpack_payloads: Vec<Vec<u8>> = events.iter().map(msgpack_bytes).collect();

    let mut json = Stats { name: "json", sizes: Vec::with_capacity(NUM_EVENTS) };
    let mut msgpack = Stats { name: "msgpack", sizes: Vec::with_capacity(NUM_EVENTS) };
    let mut pb_map = Stats { name: "protobuf-map", sizes: Vec::with_capacity(NUM_EVENTS) };
    let mut pb_bytes = Stats { name: "protobuf-bytes", sizes: Vec::with_capacity(NUM_EVENTS) };
    let mut av_map = Stats { name: "avro-map", sizes: Vec::with_capacity(NUM_EVENTS) };
    let mut av_bytes = Stats { name: "avro-bytes", sizes: Vec::with_capacity(NUM_EVENTS) };

    for (i, e) in events.iter().enumerate() {
        json.sizes.push(json_payloads[i].len());
        msgpack.sizes.push(msgpack_payloads[i].len());
        pb_map.sizes.push(protobuf_map_size(e));
        pb_bytes.sizes.push(protobuf_bytes_size(e));
        av_map.sizes.push(avro_map_size(e, &avro_map_s));
        av_bytes.sizes.push(avro_bytes_size(e, &avro_bytes_s));
    }

    let all = [&json, &msgpack, &pb_map, &pb_bytes, &av_map, &av_bytes];
    let json_total = json.total() as f64;

    println!(
        "{:<16} {:>12} {:>11} {:>10} {:>10} {:>10} {:>10} {:>8}",
        "format", "total", "mean", "min", "p50", "p90", "max", "vs json"
    );
    println!("{}", "-".repeat(94));
    for s in all {
        let mut sorted = s.sizes.clone();
        sorted.sort_unstable();
        let ratio = s.total() as f64 / json_total;
        println!(
            "{:<16} {:>12} {:>11} {:>10} {:>10} {:>10} {:>10} {:>7.1}%",
            s.name,
            human(s.total() as f64),
            human(s.mean()),
            human(*sorted.first().unwrap() as f64),
            human(s.percentile(&sorted, 50.0) as f64),
            human(s.percentile(&sorted, 90.0) as f64),
            human(*sorted.last().unwrap() as f64),
            ratio * 100.0,
        );
    }

    // Size-bucket breakdown of mean bytes per event.
    let buckets: [(&str, usize, usize); 4] = [
        ("< 2 KB", 0, 2_048),
        ("2 KB .. 32 KB", 2_048, 32_768),
        ("32 KB .. 128 KB", 32_768, 131_072),
        (">= 128 KB", 131_072, usize::MAX),
    ];
    println!("\nMean bytes per event by JSON payload size bucket:\n");
    println!(
        "{:<18} {:>8} {:>11} {:>11} {:>13} {:>14} {:>11} {:>11}",
        "bucket", "count", "json", "msgpack", "protobuf-map", "protobuf-bytes", "avro-map", "avro-bytes"
    );
    println!("{}", "-".repeat(102));
    for (label, lo, hi) in buckets {
        let idxs: Vec<usize> = json
            .sizes
            .iter()
            .enumerate()
            .filter(|(_, &sz)| sz >= lo && sz < hi)
            .map(|(i, _)| i)
            .collect();
        if idxs.is_empty() {
            continue;
        }
        let mean_of = |s: &Stats| -> f64 {
            idxs.iter().map(|&i| s.sizes[i] as f64).sum::<f64>() / idxs.len() as f64
        };
        println!(
            "{:<18} {:>8} {:>11} {:>11} {:>13} {:>14} {:>11} {:>11}",
            label,
            idxs.len(),
            human(mean_of(&json)),
            human(mean_of(&msgpack)),
            human(mean_of(&pb_map)),
            human(mean_of(&pb_bytes)),
            human(mean_of(&av_map)),
            human(mean_of(&av_bytes)),
        );
    }

    println!("\nNotes:");
    println!("  * sizes are UNCOMPRESSED serialized bytes per event");
    println!("  * protobuf via prost::Message::encoded_len(); avro via raw to_avro_datum() (no container header)");
    println!("  * msgpack via rmp_serde (schemaless binary — same dynamic shape as JSON, no schema registry)");
    println!("  * `-map` keeps property maps native (values stringified); `-bytes` stores the map's JSON in one bytes field");

    // -----------------------------------------------------------------------
    // Compression stage.
    // -----------------------------------------------------------------------
    println!("\n{}", "=".repeat(82));
    println!("COMPRESSION (per-message, the app-level-compression scenario)");
    println!("{}", "=".repeat(82));

    let json_codecs = run_all_codecs(&json_payloads);
    print_comp_table("JSON payload — per-message compression:", json_total, &json_codecs);

    let msgpack_total = msgpack.total() as f64;
    let msgpack_codecs = run_all_codecs(&msgpack_payloads);
    print_comp_table("MessagePack payload — per-message compression:", msgpack_total, &msgpack_codecs);

    // Per-message vs Kafka-style batched compression (shared cross-message redundancy).
    println!("\nPer-message vs batched (~1 MiB batches) compression of the JSON payload:");
    println!("  (Kafka compresses per produce-batch, so batched is the realistic on-broker ratio)");
    let batches = batch_payloads(&json_payloads, 1_048_576);
    println!("  batched into {} chunks of ~1 MiB", batches.len());
    println!("{:<18} {:>14} {:>14}", "codec", "per-message", "batched");
    println!("{}", "-".repeat(48));
    for (label, lvl) in [("lz4", None::<i32>), ("zstd-3", Some(3)), ("zstd-9", Some(9))] {
        let (pm, bt) = match lvl {
            None => (
                run_codec("lz4", &json_payloads, |d| lz4_flex::compress_prepend_size(d), |d| lz4_flex::decompress_size_prepended(d).unwrap()),
                run_codec("lz4", &batches, |d| lz4_flex::compress_prepend_size(d), |d| lz4_flex::decompress_size_prepended(d).unwrap()),
            ),
            Some(l) => (
                run_codec("zstd", &json_payloads, move |d| zstd::stream::encode_all(d, l).unwrap(), |d| zstd::stream::decode_all(d).unwrap()),
                run_codec("zstd", &batches, move |d| zstd::stream::encode_all(d, l).unwrap(), |d| zstd::stream::decode_all(d).unwrap()),
            ),
        };
        println!("{:<18} {:>13.2}x {:>13.2}x", label, pm.overall_ratio(), bt.overall_ratio());
    }

    // After-compression convergence across serialization formats (zstd-3, per-message).
    let pb_bytes_payloads: Vec<Vec<u8>> = events.iter().map(protobuf_bytes_encode).collect();
    let av_bytes_payloads: Vec<Vec<u8>> = events.iter().map(|e| avro_bytes_encode(e, &avro_bytes_s)).collect();
    println!("\nDo formats still differ AFTER compression? (zstd-3, per-message)");
    println!("{:<18} {:>14} {:>10}", "format", "compressed", "vs json");
    println!("{}", "-".repeat(46));
    let z3 = |p: &[Vec<u8>]| run_codec("zstd", p, |d| zstd::stream::encode_all(d, 3).unwrap(), |d| zstd::stream::decode_all(d).unwrap());
    let json_z = z3(&json_payloads);
    let json_z_total = json_z.total_out as f64;
    for (name, res) in [
        ("json", &json_z),
        ("msgpack", &z3(&msgpack_payloads)),
        ("protobuf-bytes", &z3(&pb_bytes_payloads)),
        ("avro-bytes", &z3(&av_bytes_payloads)),
    ] {
        println!(
            "{:<18} {:>14} {:>9.1}%",
            name,
            human(res.total_out as f64),
            res.total_out as f64 / json_z_total * 100.0,
        );
    }

    println!("\nCompression notes:");
    println!("  * ratio/MB/s computed over all {NUM_EVENTS} events; MB/s is uncompressed input throughput, single-threaded");
    println!("  * gzip/snappy/lz4/zstd are exactly Kafka's native compression.type options; brotli is a non-Kafka reference");
    println!("  * per-message understates Kafka's real ratio — batch compression shares redundancy across events");
}
