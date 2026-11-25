// Mirrors cli/src/sourcemaps/content.rs, source_pairs.rs and inject.rs; keep byte output identical.
// The rules only hog has are marked where they apply.

use anyhow::{anyhow, Result};
use magic_string::{GenerateDecodedMapOptions, MagicString};
use serde::{
    de::{self, IgnoredAny, MapAccess, Visitor},
    Deserialize, Deserializer, Serialize,
};
use serde_json::Value;
use sourcemap::SourceMap;
use std::{
    collections::BTreeMap,
    fs,
    path::{Component, Path, PathBuf},
};

use crate::{
    constant::{
        CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CHUNK_ID_NAMESPACE, CODE_SNIPPET_TEMPLATE,
        CODE_SNIPPET_WITH_RELEASE_TEMPLATE, QUOTED_CHUNKID_PLACEHOLDER, RELEASE_ID_PLACEHOLDER,
    },
    node,
};

// A release id longer than this between the snippet halves is not one hog or posthog-cli wrote.
const MAX_RELEASE_ID_LITERAL_BYTES: usize = 256;
pub const SOURCEMAP_REFERENCE_PREFIXES: [&str; 2] =
    ["//# sourceMappingURL=", "//@ sourceMappingURL="];
pub const CHUNK_ID_COMMENT: &str = "//# chunkId=";
pub const DEBUG_ID_COMMENT: &str = "//# debugId=";

fn build_code_snippet(chunk_id: &str, release_id: Option<&str>) -> Result<String> {
    let Some(release_id) = release_id else {
        return substitute_chunk_id(CODE_SNIPPET_TEMPLATE, chunk_id);
    };
    Ok(
        substitute_chunk_id(CODE_SNIPPET_WITH_RELEASE_TEMPLATE, chunk_id)?
            .replace(RELEASE_ID_PLACEHOLDER, &serde_json::to_string(release_id)?),
    )
}

fn substitute_chunk_id(template: &str, chunk_id: &str) -> Result<String> {
    Ok(template.replace(
        QUOTED_CHUNKID_PLACEHOLDER,
        &serde_json::to_string(chunk_id)?,
    ))
}

struct ReleaseSnippetSpan {
    start: usize,
    end: usize,
    release_id_start: usize,
    release_id_end: usize,
}

fn find_release_snippet(source: &str, chunk_id: &str) -> Option<ReleaseSnippetSpan> {
    let (prefix, suffix) = CODE_SNIPPET_WITH_RELEASE_TEMPLATE
        .split_once(RELEASE_ID_PLACEHOLDER)
        .expect("release template has a release id placeholder");
    let suffix = substitute_chunk_id(suffix, chunk_id).ok()?;
    let start = source.find(prefix)?;
    let release_id_start = start + prefix.len();
    let release_id_len = source[release_id_start..].find(&suffix)?;
    if release_id_len > MAX_RELEASE_ID_LITERAL_BYTES {
        return None;
    }
    let release_id_end = release_id_start + release_id_len;
    Some(ReleaseSnippetSpan {
        start,
        end: release_id_end + suffix.len(),
        release_id_start,
        release_id_end,
    })
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceMapContent {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub release_id: Option<String>,
    #[serde(alias = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>,
    #[serde(rename = "debugId", skip_serializing_if = "Option::is_none")]
    pub debug_id: Option<String>,
    #[serde(flatten)]
    pub fields: BTreeMap<String, Value>,
}

impl SourceMapContent {
    fn apply_adjustment(&mut self, adjustment: SourceMap) -> Result<()> {
        let new_content = {
            let content = serde_json::to_string(&*self)?.into_bytes();
            let mut map = sourcemap::decode_slice(content.as_slice())
                .map_err(|err| anyhow!("Failed to parse sourcemap: {err}"))?;
            if let sourcemap::DecodedMap::Index(indexed) = &mut map {
                let replacement = indexed
                    .flatten()
                    .map_err(|err| anyhow!("Failed to flatten sourcemap: {err}"))?;
                map = sourcemap::DecodedMap::Regular(replacement);
            };
            let original = match &mut map {
                sourcemap::DecodedMap::Regular(m) => m,
                sourcemap::DecodedMap::Hermes(m) => m,
                sourcemap::DecodedMap::Index(_) => unreachable!(),
            };
            original.adjust_mappings(&adjustment);
            let mut content = content;
            content.clear();
            original.to_writer(&mut content)?;
            serde_json::from_slice::<SourceMapContent>(&content)?
        };
        let mut old = std::mem::replace(self, new_content);
        self.chunk_id = old.chunk_id.take();
        self.release_id = old.release_id.take();
        self.debug_id = old.debug_id.take();
        for (key, value) in old.fields {
            if key != "sections" {
                self.fields.entry(key).or_insert(value);
            }
        }
        Ok(())
    }
}

// posthog-cli asks for the content too. `adjust_mappings` reads only the adjustment's tokens, so
// the copy of the whole bundle inside the adjustment changes no written byte.
fn magic_adjustment(magic: &mut MagicString) -> Result<SourceMap> {
    let adjustment = magic
        .generate_map(GenerateDecodedMapOptions {
            include_content: false,
            ..Default::default()
        })
        .map_err(|err| anyhow!("Failed to generate source map: {err}"))?;
    SourceMap::from_slice(
        adjustment
            .to_string()
            .map_err(|err| anyhow!("Failed to serialize source map: {err}"))?
            .as_bytes(),
    )
    .map_err(|err| anyhow!("Failed to parse adjustment sourcemap: {err}"))
}

pub struct SourcePair {
    // Canonical, because hog reports this path and writes the bundle back to it.
    pub source_path: PathBuf,
    pub map_path: PathBuf,
    pub source: String,
    pub map: SourceMapContent,
}

pub enum Unreadable {
    NoSourcemap,
    Skipped(String),
    Outside(PathBuf),
}

impl SourceMapContent {
    pub fn serialize(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(self)?)
    }

    // A map without mappings, sources and names symbolicates nothing. An index map is empty only
    // when every section is, because its own top-level fields are always empty.
    pub fn is_empty(&self) -> bool {
        is_map_empty(|key| self.fields.get(key))
    }
}

fn is_map_empty<'a>(get: impl Fn(&str) -> Option<&'a Value>) -> bool {
    let mappings_empty = get("mappings")
        .and_then(Value::as_str)
        .is_none_or(str::is_empty);
    let sources_empty = get("sources")
        .and_then(Value::as_array)
        .is_none_or(Vec::is_empty);
    let names_empty = get("names")
        .and_then(Value::as_array)
        .is_none_or(Vec::is_empty);
    let sections_empty = get("sections")
        .and_then(Value::as_array)
        .is_none_or(|sections| sections.iter().all(is_section_empty));

    mappings_empty && sources_empty && names_empty && sections_empty
}

fn is_section_empty(section: &Value) -> bool {
    let Some(map) = section.get("map").and_then(Value::as_object) else {
        return true;
    };
    is_map_empty(|key| map.get(key))
}

// `roots` are the selected folders in canonical form, as `cleanup::canonical_roots` returns them.
pub fn read_pair(
    path: &Path,
    public_path_prefix: Option<&str>,
    roots: &[PathBuf],
) -> Result<SourcePair, Unreadable> {
    let skipped = |reason: String| Unreadable::Skipped(reason);

    let source_path = dunce::canonicalize(path).map_err(|error| {
        skipped(format!(
            "failed to read source: {}",
            node::message(&error, "lstat", path)
        ))
    })?;
    let source = node::read_text(&source_path)
        .map_err(|message| skipped(format!("failed to read source: {message}")))?;

    let map_path = find_sourcemap(
        &source_path,
        sourcemap_reference(&source),
        public_path_prefix,
    )
    .map_err(|_| skipped("the sourcemap reference is not valid UTF-8 once decoded".to_string()))?
    .ok_or(Unreadable::NoSourcemap)?;

    // Only hog: a bundle can name any file as its map, such as a file elsewhere on the machine or a
    // device like /dev/zero that never ends, and hog reads, rewrites and can delete that map. So a
    // map is opened only when it resolves inside a selected folder.
    match dunce::canonicalize(&map_path) {
        Ok(real_map_path) if is_within_roots(roots, &real_map_path) => {}
        Ok(real_map_path) => return Err(Unreadable::Outside(real_map_path)),
        Err(_) => return Err(Unreadable::Outside(map_path)),
    }

    let map: SourceMapContent = node::read(&map_path)
        .and_then(|bytes| serde_json::from_slice(&bytes).map_err(|error| error.to_string()))
        .map_err(|message| skipped(format!("failed to read sourcemap: {message}")))?;

    // posthog-cli would rewrite any JSON object the reference names, such as a settings file next
    // to the build.
    if !is_sourcemap(&map) {
        return Err(skipped(
            "the file its sourceMappingURL names isn't a sourcemap: it has no mappings".to_string(),
        ));
    }

    Ok(SourcePair {
        source_path,
        map_path,
        source,
        map,
    })
}

// By path component, as `isInside` in hog/src/core/paths.ts, so a folder named `..maps` is inside.
fn is_within_roots(roots: &[PathBuf], path: &Path) -> bool {
    roots.iter().any(|root| {
        path.strip_prefix(root)
            .is_ok_and(|within| !within.as_os_str().is_empty())
    })
}

// A sourcemap always has `mappings`, or `sections` when it is an index map.
pub fn is_sourcemap(map: &SourceMapContent) -> bool {
    map.fields.contains_key("mappings") || map.fields.contains_key("sections")
}

pub fn has_sourcemap(path: &Path, public_path_prefix: Option<&str>) -> bool {
    let Ok(source) = node::read_text(path) else {
        return false;
    };

    matches!(
        find_sourcemap(path, sourcemap_reference(&source), public_path_prefix),
        Ok(Some(_))
    )
}

// posthog-cli refuses to upload a Hermes map without this key, so it is what tells the map the
// Hermes compiler composed apart from Metro's packager map.
const HERMES_FUNCTION_OFFSETS: &str = "x_hermes_function_offsets";

pub fn is_composed_map(path: &Path) -> bool {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<ComposedProbe>(&bytes).ok())
        .is_some_and(|probe| probe.0)
}

// Discovery asks this of every `.map` in a build, so values are skipped, not built. It fails where
// reading a `SourceMapContent` fails, so it agrees with that on what counts as a map.
struct ComposedProbe(bool);

impl<'de> Deserialize<'de> for ComposedProbe {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_map(ComposedProbeVisitor)
    }
}

struct ComposedProbeVisitor;

impl<'de> Visitor<'de> for ComposedProbeVisitor {
    type Value = ComposedProbe;

    fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("a sourcemap object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<ComposedProbe, A::Error> {
        let mut typed_seen = [false; 3];
        let mut composed = false;
        while let Some(key) = map.next_key::<String>()? {
            let typed = match key.as_str() {
                "release_id" => Some(0),
                "chunk_id" | "chunkId" => Some(1),
                "debugId" => Some(2),
                _ => None,
            };

            match typed {
                Some(index) => {
                    if std::mem::replace(&mut typed_seen[index], true) {
                        return Err(de::Error::custom(format!("duplicate field `{key}`")));
                    }
                    map.next_value::<Option<String>>()?;
                }
                None => {
                    composed |= key == HERMES_FUNCTION_OFFSETS;
                    map.next_value::<IgnoredAny>()?;
                }
            }
        }
        Ok(ComposedProbe(composed))
    }
}

impl SourcePair {
    fn comment_value(&self, prefix: &str) -> Option<String> {
        self.source
            .lines()
            .rev()
            .find(|line| line.starts_with(prefix))
            .and_then(|line| line.split_once('=').map(|(_, value)| value.to_string()))
    }

    pub fn chunk_id(&self) -> Option<String> {
        self.comment_value(CHUNK_ID_COMMENT)
    }

    pub fn source_debug_id(&self) -> Option<String> {
        self.comment_value(DEBUG_ID_COMMENT)
    }

    // The chunk's own comment wins, because several chunks can share one sourcemap.
    pub fn debug_id(&self) -> Option<String> {
        self.source_debug_id().or_else(|| self.map.debug_id.clone())
    }

    // The two snippets differ in length, so which one a bundle carries decides every generated
    // column its sourcemap records.
    pub fn has_release_snippet(&self, chunk_id: &str) -> bool {
        find_release_snippet(&self.source, chunk_id).is_some()
    }

    pub fn injected_release_id(&self) -> Option<String> {
        let chunk_id = self.chunk_id()?;
        let span = find_release_snippet(&self.source, &chunk_id)?;
        serde_json::from_str(&self.source[span.release_id_start..span.release_id_end]).ok()
    }

    pub fn add_chunk_id(&mut self, chunk_id: &str, release_id: Option<&str>) -> Result<()> {
        if self.chunk_id().is_some() {
            return Err(anyhow!("Chunk ID already set"));
        }
        let mut magic = MagicString::new(&self.source);
        magic
            .prepend(&build_code_snippet(chunk_id, release_id)?)
            .map_err(|err| anyhow!("Failed to prepend code snippet: {err}"))?;
        magic
            .append(&CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, chunk_id))
            .map_err(|err| anyhow!("Failed to append chunk comment: {err}"))?;
        let adjustment = magic_adjustment(&mut magic)?;
        self.source = magic.to_string();
        if self.map.chunk_id.is_none() {
            self.map.apply_adjustment(adjustment)?;
            self.map.chunk_id = Some(chunk_id.to_string());
        }
        Ok(())
    }

    pub fn remove_chunk_id(&mut self, chunk_id: &str) -> Result<()> {
        if self.chunk_id().as_deref() != Some(chunk_id) {
            return Err(anyhow!("Chunk ID mismatch"));
        }
        let mut magic = MagicString::new(&self.source);
        let chunk_comment = CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, chunk_id);
        if let Some(start) = self.source.find(&chunk_comment) {
            magic
                .remove(start as i64, (start + chunk_comment.len()) as i64)
                .map_err(|err| anyhow!("Failed to remove chunk comment: {err}"))?;
        }
        let code_snippet = substitute_chunk_id(CODE_SNIPPET_TEMPLATE, chunk_id)?;
        if let Some(start) = self.source.find(&code_snippet) {
            magic
                .remove(start as i64, (start + code_snippet.len()) as i64)
                .map_err(|err| anyhow!("Failed to remove code snippet {err}"))?;
        } else if let Some(span) = find_release_snippet(&self.source, chunk_id) {
            magic
                .remove(span.start as i64, span.end as i64)
                .map_err(|err| anyhow!("Failed to remove code snippet {err}"))?;
        }
        let adjustment = magic_adjustment(&mut magic)?;
        self.source = magic.to_string();
        self.map.apply_adjustment(adjustment)?;
        self.map.chunk_id = None;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Injected,
    ReleaseUpdated,
    Unchanged,
}

fn adopted_debug_id(pair: &SourcePair, warnings: &mut Vec<String>) -> Option<String> {
    let display = pair.source_path.display();
    let source_id = pair.source_debug_id();
    let id = source_id.clone().or_else(|| pair.map.debug_id.clone())?;
    if let (Some(source_id), Some(map_id)) = (&source_id, &pair.map.debug_id) {
        if source_id != map_id {
            warnings.push(format!(
                "{display}: the chunk and its sourcemap have different debug ids. Using the chunk's."
            ));
        }
    }
    if uuid::Uuid::parse_str(&id).is_ok() {
        return Some(id);
    }
    warnings.push(format!(
        "{display}: ignoring the malformed debug id {} and deriving a chunk id from the content.",
        js_string(&id)
    ));
    None
}

// `JSON.stringify` of a string. serde_json escapes the same characters except U+2028 and U+2029,
// which neither escapes, and lone surrogates, which a Rust string cannot hold.
fn js_string(text: &str) -> String {
    serde_json::to_string(text).expect("a string serializes")
}

pub fn inject_event_mode(
    pair: &mut SourcePair,
    release_id: Option<&str>,
    warnings: &mut Vec<String>,
) -> Result<(Action, String)> {
    let Some(existing) = pair.chunk_id() else {
        let chunk_id = adopted_debug_id(pair, warnings).unwrap_or_else(|| {
            uuid::Uuid::new_v5(&CHUNK_ID_NAMESPACE, pair.source.as_bytes()).to_string()
        });
        pair.add_chunk_id(&chunk_id, release_id)?;
        return Ok((Action::Injected, chunk_id));
    };
    let Some(release_id) = release_id else {
        return Ok((Action::Unchanged, existing));
    };
    if pair.injected_release_id().as_deref() == Some(release_id) {
        return Ok((Action::Unchanged, existing));
    }
    pair.remove_chunk_id(&existing)?;
    pair.add_chunk_id(&existing, Some(release_id))?;
    Ok((Action::ReleaseUpdated, existing))
}

// A pair whose release changed gets a new chunk id, because PostHog binds a symbol set to one
// release.
pub fn inject_symbol_set_mode(
    pair: &mut SourcePair,
    release_id: Option<&str>,
    now: &uuid::Timestamp,
) -> Result<(Action, String)> {
    let existing = pair.chunk_id();
    if let Some(existing) = &existing {
        if pair.map.release_id.as_deref() == release_id {
            return Ok((Action::Unchanged, existing.clone()));
        }
    }

    let chunk_id = uuid::Uuid::new_v7(*now).to_string();
    pair.map.release_id = release_id.map(str::to_string);
    if let Some(existing) = &existing {
        pair.remove_chunk_id(existing)?;
    }
    pair.add_chunk_id(&chunk_id, None)?;

    let action = if existing.is_some() {
        Action::ReleaseUpdated
    } else {
        Action::Injected
    };
    Ok((action, chunk_id))
}

pub fn sourcemap_reference(source: &str) -> Option<&str> {
    source.lines().rev().find_map(|line| {
        let line = line.trim();
        SOURCEMAP_REFERENCE_PREFIXES
            .iter()
            .find_map(|prefix| line.strip_prefix(prefix))
    })
}

// Node's `path.join`: joins, then folds `.` and `..` without touching the disk. hog reports and
// rewrites the map at this path, so it must be spelled the way hog spells it.
fn node_join(folder: &Path, relative: &str) -> PathBuf {
    let joined = folder.join(relative);
    let mut out: Vec<Component> = Vec::new();
    for component in joined.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => match out.last() {
                Some(Component::Normal(_)) => {
                    out.pop();
                }
                Some(Component::RootDir) | Some(Component::Prefix(_)) => {}
                _ => out.push(component),
            },
            other => out.push(other),
        }
    }
    out.iter().collect()
}

// Err means the decoded reference is not valid UTF-8.
pub fn find_sourcemap(
    source_path: &Path,
    reference: Option<&str>,
    public_path_prefix: Option<&str>,
) -> Result<Option<PathBuf>, ()> {
    let folder = source_path.parent().unwrap_or(Path::new(""));
    let mut candidates = Vec::new();
    if let Some(reference) = reference {
        let decoded = urlencoding::decode(reference).map_err(|_| ())?;
        let resolve = |path: &str| {
            if Path::new(path).is_absolute() {
                PathBuf::from(path)
            } else {
                node_join(folder, path)
            }
        };
        candidates.push(resolve(&decoded));
        if let Some(prefix) = public_path_prefix {
            for prefix in [prefix.to_string(), format!("{prefix}/")] {
                if let Some(rest) = decoded.strip_prefix(prefix.as_str()) {
                    candidates.push(resolve(rest));
                }
            }
        }
    }
    let mut guessed = source_path.as_os_str().to_owned();
    guessed.push(".map");
    candidates.push(PathBuf::from(guessed));
    Ok(candidates.into_iter().find(|candidate| candidate.exists()))
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::{ffi::CString, os::unix::ffi::OsStrExt, sync::mpsc, thread, time::Duration};

    const MAP: &str = r#"{"version":3,"sources":["a.ts"],"names":[],"mappings":"AAAA"}"#;
    const READ_TIMEOUT: Duration = Duration::from_secs(10);
    const FIFO_MODE: libc::mode_t = 0o600;

    fn scratch() -> PathBuf {
        let folder = std::env::temp_dir().join(format!("hog-worker-pair-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&folder).expect("the scratch folder is created");
        dunce::canonicalize(folder).unwrap()
    }

    fn make_fifo(path: &Path) {
        let name = CString::new(path.as_os_str().as_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), FIFO_MODE) }, 0);
    }

    // Opening a FIFO to read blocks until a writer opens it, and /dev/zero never ends, so a worker
    // that opened either would never answer. The read runs on a thread to fail the test instead, and
    // None means it timed out.
    fn read_bundle(bundle: &Path, roots: &[PathBuf]) -> Option<Result<SourcePair, Unreadable>> {
        let (bundle, roots) = (bundle.to_path_buf(), roots.to_vec());
        let (send, receive) = mpsc::channel();
        thread::spawn(move || {
            let _ = send.send(read_pair(&bundle, None, &roots));
        });

        receive.recv_timeout(READ_TIMEOUT).ok()
    }

    #[test]
    fn a_map_outside_the_roots_is_never_opened() {
        let folder = scratch();
        let dist = folder.join("dist");
        fs::create_dir(&dist).unwrap();
        fs::write(folder.join("outside.js.map"), MAP).unwrap();
        std::os::unix::fs::symlink(folder.join("outside.js.map"), dist.join("link.js.map"))
            .unwrap();
        make_fifo(&folder.join("map.fifo"));
        let bundle = dist.join("a.js");

        let cases = [
            ("/dev/zero", PathBuf::from("/dev/zero")),
            ("../map.fifo", folder.join("map.fifo")),
            ("../outside.js.map", folder.join("outside.js.map")),
            ("link.js.map", folder.join("outside.js.map")),
        ];
        for (reference, expected) in cases {
            fs::write(&bundle, format!("a();\n//# sourceMappingURL={reference}\n")).unwrap();

            match read_bundle(&bundle, std::slice::from_ref(&dist)) {
                Some(Err(Unreadable::Outside(path))) => assert_eq!(path, expected, "{reference}"),
                None => panic!("read_pair opened {reference} and never answered"),
                Some(_) => panic!("{reference} should resolve outside the roots"),
            }
        }

        fs::write(dist.join("a.js.map"), MAP).unwrap();
        fs::write(&bundle, "a();\n//# sourceMappingURL=a.js.map\n").unwrap();
        let inside = read_bundle(&bundle, std::slice::from_ref(&dist));

        assert!(matches!(inside, Some(Ok(pair)) if pair.map_path == dist.join("a.js.map")));
        fs::remove_dir_all(folder).unwrap();
    }
}
