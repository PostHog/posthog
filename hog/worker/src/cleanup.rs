// `--delete-after`: once an upload succeeded, drop the sourcemap references from the bundles and
// delete the maps, so they never ship to users. A file that changed since it was fingerprinted is
// left alone, and a map is only deleted when every bundle that points at it was cleaned.

use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{self, Read, Seek, SeekFrom, Write},
    ops::Range,
    path::{Path, PathBuf},
};

use crate::{
    node,
    pair::{self, SourceMapContent, SourcePair},
    upload::content_hash,
};

const CSS_SOURCEMAP_REFERENCE_PREFIX: &str = "/*# sourceMappingURL=";
const CSS_COMMENT_END: &str = "*/";
const STAGED_SUFFIX: &str = "posthog-delete";
// Stands in for the hash of a map that can't be read. No fingerprint equals it.
const UNREADABLE_MAP_HASH: &str = "";

#[derive(Clone, Copy)]
enum Kind {
    Js,
    Css,
}

// A bundle and its map as they were when hog read them. Maps are hashed over their canonical
// serialization, so the comparison holds across whitespace and key order.
pub struct Target {
    source_path: PathBuf,
    map_path: PathBuf,
    source_hash: String,
    map_hash: String,
    kind: Kind,
}

pub fn js_target(pair: &SourcePair) -> Result<Target, String> {
    Ok(Target {
        source_path: pair.source_path.clone(),
        map_path: pair.map_path.clone(),
        source_hash: content_hash([pair.source.as_bytes()]),
        map_hash: map_hash(&pair.map)?,
        kind: Kind::Js,
    })
}

fn map_hash(map: &SourceMapContent) -> Result<String, String> {
    let canonical = map.serialize().map_err(|error| error.to_string())?;
    Ok(content_hash([canonical]))
}

// A stylesheet under the selected paths. `found` is None when its sourcemap reference can't be
// read, which hog reports when it cleans up.
pub struct CssCandidate {
    file: String,
    found: Option<CssFound>,
}

struct CssFound {
    source_path: PathBuf,
    source_hash: String,
    map_path: PathBuf,
}

impl CssCandidate {
    pub fn map_path(&self) -> Option<&Path> {
        self.found.as_ref().map(|found| found.map_path.as_path())
    }
}

// None for a stylesheet without a sourcemap, which needs no cleanup.
pub fn css_candidate(file: &str, public_path_prefix: Option<&str>) -> Option<CssCandidate> {
    let find = || -> Result<Option<CssFound>, ()> {
        let source_path = dunce::canonicalize(file).map_err(|_| ())?;
        let source = node::read_text(&source_path).map_err(|_| ())?;
        let map_path =
            pair::find_sourcemap(&source_path, css_reference(&source), public_path_prefix)?;

        Ok(map_path.map(|map_path| CssFound {
            source_hash: content_hash([source.as_bytes()]),
            source_path,
            map_path,
        }))
    };

    match find() {
        Ok(None) => None,
        Ok(found) => Some(CssCandidate {
            file: file.to_string(),
            found,
        }),
        Err(()) => Some(CssCandidate {
            file: file.to_string(),
            found: None,
        }),
    }
}

// A stylesheet's map is cleaned up only when it resolves inside a selected path, so a stylesheet
// can't make hog delete a file elsewhere. A JSON file that isn't a sourcemap is left alone.
// Err is the warning hog shows.
pub fn css_target(candidate: &CssCandidate, roots: &[PathBuf]) -> Result<Option<Target>, String> {
    let Some(found) = &candidate.found else {
        return Err(format!(
            "Skipping sourcemap cleanup for {}: its sourcemap reference can't be read.",
            candidate.file
        ));
    };

    let Some(map) = load_map(&found.map_path) else {
        return Ok(None);
    };
    if !pair::is_sourcemap(&map) {
        return Ok(None);
    }

    let canonical_map =
        dunce::canonicalize(&found.map_path).unwrap_or_else(|_| found.map_path.clone());
    if !roots.iter().any(|root| is_inside(root, &canonical_map)) {
        return Err(format!(
            "Skipping CSS sourcemap cleanup for {} because it resolves outside the selected paths.",
            found.map_path.display()
        ));
    }

    let Ok(map_hash) = map_hash(&map) else {
        return Ok(None);
    };
    Ok(Some(Target {
        source_path: found.source_path.clone(),
        map_path: found.map_path.clone(),
        source_hash: found.source_hash.clone(),
        map_hash,
        kind: Kind::Css,
    }))
}

// A selected file stands for the folder it is in.
pub fn canonical_roots(roots: &[String]) -> Result<Vec<PathBuf>, String> {
    roots
        .iter()
        .map(|root| {
            let root = Path::new(root);
            let canonical =
                dunce::canonicalize(root).map_err(|error| node::message(&error, "lstat", root))?;
            match canonical.parent() {
                Some(parent) if canonical.is_file() => Ok(parent.to_path_buf()),
                _ => Ok(canonical),
            }
        })
        .collect()
}

// Node's `path.relative` gives a path that starts with `..` for a file outside the folder, and
// hog's ignore patterns test for that prefix. So a file inside whose name starts with two dots
// counts as outside here too.
fn is_inside(root: &Path, path: &Path) -> bool {
    path.strip_prefix(root)
        .is_ok_and(|within| !within.to_string_lossy().starts_with(".."))
}

fn load_map(path: &Path) -> Option<SourceMapContent> {
    serde_json::from_slice(&fs::read(path).ok()?).ok()
}

// JavaScript's `String.prototype.trim` set, which the stylesheet rules were written against. It
// counts U+FEFF as whitespace and U+0085 not, the reverse of Rust's `char::is_whitespace`.
fn is_js_whitespace(c: char) -> bool {
    (c.is_whitespace() && c != '\u{85}') || c == '\u{feff}'
}

fn is_js_blank(text: &str) -> bool {
    text.chars().all(is_js_whitespace)
}

// The last `/*# sourceMappingURL=... */` comment outside a string.
fn css_reference_range(content: &str) -> Option<Range<usize>> {
    let bytes = content.as_bytes();
    let mut index = 0;
    let mut quote = None;
    let mut escaped = false;
    let mut found = None;

    while index < bytes.len() {
        if escaped {
            escaped = false;
            index += 1;
            continue;
        }

        if let Some(active_quote) = quote {
            if bytes[index] == b'\\' {
                escaped = true;
            } else if bytes[index] == active_quote {
                quote = None;
            }
            index += 1;
            continue;
        }

        if bytes[index] == b'\\' {
            escaped = true;
            index += 1;
            continue;
        }

        match bytes[index] {
            b'\'' | b'"' => {
                quote = Some(bytes[index]);
                index += 1;
            }
            b'/' if bytes.get(index + 1) == Some(&b'*') => {
                let comment_end = content[index + 2..]
                    .find(CSS_COMMENT_END)
                    .map(|end| index + 2 + end + CSS_COMMENT_END.len())?;
                if content[index..].starts_with(CSS_SOURCEMAP_REFERENCE_PREFIX) {
                    found = Some(index..comment_end);
                }
                index = comment_end;
            }
            _ => index += 1,
        }
    }

    found
}

fn css_reference(content: &str) -> Option<&str> {
    let range = css_reference_range(content)?;
    let reference_start = range.start + CSS_SOURCEMAP_REFERENCE_PREFIX.len();
    Some(
        content[reference_start..range.end - CSS_COMMENT_END.len()]
            .trim_end_matches(is_js_whitespace),
    )
}

// The whole line goes when the comment is alone on it. Otherwise only the comment does.
fn css_removal_range(content: &str) -> Option<Range<usize>> {
    let comment = css_reference_range(content)?;
    let line_start = content[..comment.start]
        .rfind('\n')
        .map_or(0, |index| index + 1);
    let line_end = content[comment.end..]
        .find('\n')
        .map_or(content.len(), |index| comment.end + index + 1);

    if is_js_blank(&content[line_start..comment.start])
        && is_js_blank(&content[comment.end..line_end])
    {
        Some(line_start..line_end)
    } else {
        Some(comment)
    }
}

// The last real line of a bundle, skipping blank lines and the chunk and debug id comments, when
// it is a `sourceMappingURL` comment: the whole line goes, newline included.
fn js_reference_range(content: &str) -> Option<Range<usize>> {
    let mut line_start = 0;
    let mut lines = Vec::new();
    for line in content.split_inclusive('\n') {
        let line_end = line_start + line.len();
        lines.push((line_start, line_end, line));
        line_start = line_end;
    }

    for (line_start, line_end, line) in lines.into_iter().rev() {
        let trimmed = line.trim();
        if trimmed.is_empty()
            || trimmed.starts_with(pair::CHUNK_ID_COMMENT)
            || trimmed.starts_with(pair::DEBUG_ID_COMMENT)
        {
            continue;
        }
        if pair::SOURCEMAP_REFERENCE_PREFIXES
            .iter()
            .any(|prefix| trimmed.starts_with(prefix))
        {
            return Some(line_start..line_end);
        }
        return None;
    }

    None
}

pub struct Cleaned {
    pub deleted_maps: Vec<String>,
    pub warnings: Vec<String>,
}

// Strips every source first, then deletes the maps. A map can be shared by several bundles, so
// its deletion needs the outcome of each: a skipped source may still reference the map. Maps are
// grouped by canonical path, because two spellings or a symlink can name one file, and each
// sharing pair holds its own copy of the map, so the fingerprint of any of them marks it as ours.
pub fn clean_up(targets: &[&Target]) -> Result<Cleaned, String> {
    let mut warnings = Vec::new();
    let mut maps: Vec<(PathBuf, HashSet<&str>)> = Vec::new();
    let mut places: HashMap<PathBuf, usize> = HashMap::new();
    let mut skipped: HashSet<usize> = HashSet::new();

    for target in targets {
        let canonical_map =
            dunce::canonicalize(&target.map_path).unwrap_or_else(|_| target.map_path.clone());
        let place = *places.entry(canonical_map.clone()).or_insert_with(|| {
            maps.push((canonical_map, HashSet::new()));
            maps.len() - 1
        });
        maps[place].1.insert(&target.map_hash);

        if !strip_verified_source(target, &mut warnings)? {
            skipped.insert(place);
        }
    }

    let mut deleted_maps = Vec::new();
    for (place, (path, fingerprints)) in maps.iter().enumerate() {
        if skipped.contains(&place) {
            warnings.push(format!(
                "Skipping sourcemap deletion for {}: a source referencing it was skipped.",
                path.display()
            ));
            continue;
        }
        if delete_verified_map(path, fingerprints, &mut warnings)? {
            deleted_maps.push(path.to_string_lossy().into_owned());
        }
    }

    Ok(Cleaned {
        deleted_maps,
        warnings,
    })
}

fn is_missing(error: &io::Error) -> bool {
    error.kind() == io::ErrorKind::NotFound
}

fn missing_warning(target: &Target) -> String {
    format!(
        "Skipping cleanup for {}: the file no longer exists.",
        target.source_path.display()
    )
}

// The content when it is still what hog read. Ok(None) leaves a warning.
fn verified(
    target: &Target,
    bytes: Vec<u8>,
    warnings: &mut Vec<String>,
) -> Result<Option<String>, String> {
    let content = node::utf8(bytes)?;
    if content_hash([content.as_bytes()]) != target.source_hash {
        warnings.push(format!(
            "Skipping cleanup for {}: the file changed since it was uploaded.",
            target.source_path.display()
        ));
        return Ok(None);
    }
    Ok(Some(content))
}

// A source that needs no change is only read, so it needs no write access. A bundler can replace
// a file while hog cleans up (write new, rename over the path), so the write goes through a handle
// that is verified again, and a replacement is never overwritten with old bytes.
fn strip_verified_source(target: &Target, warnings: &mut Vec<String>) -> Result<bool, String> {
    let path = &target.source_path;
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if is_missing(&error) => {
            warnings.push(missing_warning(target));
            return Ok(false);
        }
        Err(error) => return Err(node::message(&error, "open", path)),
    };
    let Some(mut content) = verified(target, bytes, warnings)? else {
        return Ok(false);
    };

    let range = match target.kind {
        Kind::Js => js_reference_range(&content),
        Kind::Css => css_removal_range(&content),
    };
    let Some(range) = range else {
        return Ok(true);
    };

    let mut file = match fs::OpenOptions::new().read(true).write(true).open(path) {
        Ok(file) => file,
        Err(error) if is_missing(&error) => {
            warnings.push(missing_warning(target));
            return Ok(false);
        }
        Err(error) => return Err(node::message(&error, "open", path)),
    };
    let mut current = Vec::new();
    file.read_to_end(&mut current)
        .map_err(|error| node::message(&error, "read", path))?;
    if verified(target, current, warnings)?.is_none() {
        return Ok(false);
    }

    content.replace_range(range, "");
    file.set_len(0)
        .and_then(|_| file.seek(SeekFrom::Start(0)))
        .and_then(|_| file.write_all(content.as_bytes()))
        .map_err(|error| node::message(&error, "write", path))?;
    Ok(true)
}

fn staged_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(format!(".{}.{STAGED_SUFFIX}", std::process::id()));
    PathBuf::from(name)
}

// The map is renamed aside before it is verified, so the check and the removal see the same file,
// and a map the bundler writes to the path in between stays.
fn delete_verified_map(
    path: &Path,
    fingerprints: &HashSet<&str>,
    warnings: &mut Vec<String>,
) -> Result<bool, String> {
    let staged = staged_path(path);
    match fs::rename(path, &staged) {
        Ok(()) => {}
        Err(error) if is_missing(&error) => return Ok(false),
        Err(error) => return Err(node::rename_message(&error, path, &staged)),
    }

    let current = load_map(&staged)
        .and_then(|map| map_hash(&map).ok())
        .unwrap_or_else(|| UNREADABLE_MAP_HASH.to_string());
    let remove_staged =
        || fs::remove_file(&staged).map_err(|error| node::message(&error, "unlink", &staged));
    if fingerprints.contains(current.as_str()) {
        remove_staged()?;
        return Ok(true);
    }

    warnings.push(format!(
        "Skipping sourcemap deletion for {}: the map changed since it was uploaded.",
        path.display()
    ));
    // A link fails when a newer map already sits at the path. That map wins.
    match fs::hard_link(&staged, path) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => warnings.push(format!(
            "A newer sourcemap appeared at {}. Discarding the displaced copy.",
            path.display()
        )),
        Err(_) => {
            fs::rename(&staged, path)
                .map_err(|error| node::rename_message(&error, &staged, path))?;
            return Ok(false);
        }
    }
    remove_staged()?;
    Ok(false)
}
