use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

use anyhow::{bail, Result};
use posthog_symbol_data::{write_symbol_data_uncompressed, JvmBundle};
use tracing::warn;
use uuid::Uuid;
use walkdir::WalkDir;

use crate::utils::files::content_hash;

/// The file the PostHog JVM SDKs read from the classpath, and the key that holds the id they
/// send as `map_id` on each stack frame. posthog-android uses the same file and key.
pub const META_PROPERTIES_FILE: &str = "posthog-meta.properties";
pub const MAP_ID_PROPERTY: &str = "io.posthog.proguard.mapid";

// Fixed namespace for the bundle id (UUIDv5). The same sources in the same release give the same id
// on every machine and in every build, so a re-upload is skipped instead of conflicting with the
// symbol set already stored under that id.
const BUNDLE_ID_NAMESPACE: Uuid = Uuid::from_u128(0x096b_bc25_8f67_4bc9_8edc_cb21_b94f_0169);

const SOURCE_EXTENSIONS: [&str; 2] = ["java", "kt"];

// Larger files are almost always generated code, which no stack frame of the application points
// at, and they would only push the symbol set toward the server's size limit.
const MAX_SOURCE_FILE_BYTES: u64 = 1024 * 1024;

// Directories that build tools fill with build output. A build tool puts them next to the
// module's `src` directory or build file. A package directory with the same name
// (`com/acme/build`) has neither next to it, so it is kept.
const BUILD_OUTPUT_DIRS: [&str; 3] = ["build", "target", "out"];
const MODULE_MARKERS: [&str; 8] = [
    "src",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "build.sbt",
    "build.xml",
];

// Test source sets, skipped when their parent directory is `src`. No production stack frame
// points at test code, and a test class can share a package and file name with a production class.
const TEST_SOURCE_SETS: [&str; 4] = ["test", "androidTest", "testFixtures", "integrationTest"];

pub struct SourceBundle {
    pub id: String,
    pub content_hash: String,
    pub bundle: JvmBundle,
}

pub fn collect_sources(roots: &[PathBuf]) -> Result<BTreeMap<String, String>> {
    let mut candidates: BTreeMap<String, Vec<(PathBuf, String)>> = BTreeMap::new();

    for root in roots {
        if !root.is_dir() {
            bail!("Source directory {} does not exist", root.display());
        }
        // The root itself is always read, also when it is inside a build output directory.
        let walker = WalkDir::new(root).into_iter().filter_entry(|entry| {
            entry.depth() == 0
                || !(entry.file_type().is_dir() && is_skipped_directory(entry.path()))
        });
        for entry in walker {
            let entry = entry?;
            let path = entry.path();
            let is_source = path
                .extension()
                .and_then(|ext| ext.to_str())
                .is_some_and(|ext| SOURCE_EXTENSIONS.contains(&ext));
            if !entry.file_type().is_file() || !is_source {
                continue;
            }
            if entry.metadata()?.len() > MAX_SOURCE_FILE_BYTES {
                warn!(
                    "Skipping {}: it is larger than {MAX_SOURCE_FILE_BYTES} bytes",
                    path.display()
                );
                continue;
            }
            let content = match fs::read_to_string(path) {
                Ok(content) => content,
                Err(e) => {
                    warn!("Skipping {}: {e}", path.display());
                    continue;
                }
            };
            let file_name = entry.file_name().to_string_lossy();
            let key = match package_name(&content) {
                Some(package) => format!("{}/{file_name}", package.replace('.', "/")),
                None => file_name.to_string(),
            };
            candidates
                .entry(key)
                .or_default()
                .push((path.to_path_buf(), content));
        }
    }

    let mut sources = BTreeMap::new();
    for (key, files) in candidates {
        let (_, first) = &files[0];
        if files.iter().any(|(_, content)| content != first) {
            // A stack frame names only the package and the file, so PostHog cannot tell these
            // files apart. Showing no code is better than showing the code of the wrong file.
            let paths: Vec<String> = files.iter().map(|(p, _)| p.display().to_string()).collect();
            warn!(
                "Skipping {key}: {} different files have this package and file name ({})",
                files.len(),
                paths.join(", ")
            );
            continue;
        }
        sources.insert(key, first.clone());
    }
    Ok(sources)
}

/// Builds the bundle and its id. The id is derived from the bundle bytes and the hash id of the
/// release the bundle is uploaded to. The bundle bytes hold only the lookup keys and file
/// contents, never a local path, so a checkout in any directory gives the same id.
///
/// The release is part of the id because a symbol set belongs to one release, and cymbal takes
/// the release of an event from the symbol sets its frames resolved with. Unchanged sources in a
/// new release get a new symbol set, so the events of that release resolve to it, not to the
/// release that first uploaded the sources.
pub fn bundle_sources(
    sources: BTreeMap<String, String>,
    release_hash_id: Option<&str>,
) -> Result<SourceBundle> {
    let bundle = JvmBundle {
        mapping: None,
        sources,
    };
    let canonical = write_symbol_data_uncompressed(bundle.clone())?;
    // The encoded bundle determines its own length, so the bytes appended after it cannot make
    // two different bundle and release pairs give the same input.
    let mut identity = canonical.clone();
    if let Some(release_hash_id) = release_hash_id {
        identity.extend_from_slice(release_hash_id.as_bytes());
    }
    Ok(SourceBundle {
        id: Uuid::new_v5(&BUNDLE_ID_NAMESPACE, &identity).to_string(),
        // The upload compresses the bundle, and compressed bytes can differ between zstd
        // versions. Hashing the uncompressed bytes keeps the server's identical-content check
        // stable across CLI releases.
        content_hash: content_hash([&canonical]),
        bundle,
    })
}

fn is_skipped_directory(dir: &Path) -> bool {
    let (Some(name), Some(parent)) = (dir.file_name().and_then(|n| n.to_str()), dir.parent())
    else {
        return false;
    };
    if name.starts_with('.') || name == "node_modules" {
        return true;
    }
    if BUILD_OUTPUT_DIRS.contains(&name) {
        return MODULE_MARKERS
            .iter()
            .any(|marker| parent.join(marker).exists());
    }
    parent.file_name().is_some_and(|parent| parent == "src") && TEST_SOURCE_SETS.contains(&name)
}

/// The package a Java or Kotlin file declares, or `None` for the default package. Comments and
/// file annotations (`@file:JvmName("Utils")`) may come before the declaration.
pub fn package_name(source: &str) -> Option<String> {
    let mut rest = source.trim_start_matches('\u{feff}');
    loop {
        rest = rest.trim_start();
        if let Some(after) = rest.strip_prefix("//") {
            rest = after.split_once('\n').map_or("", |(_, next)| next);
        } else if let Some(after) = rest.strip_prefix("/*") {
            rest = after.split_once("*/").map_or("", |(_, next)| next);
        } else if rest.starts_with('@') {
            rest = skip_annotation(rest);
        } else {
            break;
        }
    }

    let declaration = rest.strip_prefix("package")?;
    if !declaration.starts_with(char::is_whitespace) {
        return None;
    }
    let line = declaration
        .split(['\n', ';'])
        .next()
        .unwrap_or_default()
        .split("//")
        .next()
        .unwrap_or_default()
        .split("/*")
        .next()
        .unwrap_or_default();
    let name: String = line
        .chars()
        .filter(|c| !c.is_whitespace() && *c != '`')
        .collect();
    let valid = !name.is_empty()
        && name
            .split('.')
            .all(|part| !part.is_empty() && part.chars().all(|c| c.is_alphanumeric() || c == '_'));
    valid.then_some(name)
}

fn skip_annotation(source: &str) -> &str {
    let after_at = &source[1..];
    let name_end = after_at
        .find(|c: char| !(c.is_alphanumeric() || matches!(c, '_' | '.' | ':')))
        .unwrap_or(after_at.len());
    let after_name = &after_at[name_end..];
    match after_name.trim_start().chars().next() {
        Some(open @ ('(' | '[')) => skip_balanced(after_name.trim_start(), open),
        _ => after_name,
    }
}

// Skips one bracketed group, such as an annotation's arguments. Brackets inside string literals
// do not count, so `@file:Suppress("a)b")` ends at the real closing bracket.
fn skip_balanced(source: &str, open: char) -> &str {
    let close = if open == '(' { ')' } else { ']' };
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for (index, c) in source.char_indices() {
        if in_string {
            match c {
                _ if escaped => escaped = false,
                '\\' => escaped = true,
                '"' => in_string = false,
                _ => {}
            }
            continue;
        }
        match c {
            '"' => in_string = true,
            c if c == open => depth += 1,
            c if c == close => {
                depth -= 1;
                if depth == 0 {
                    return &source[index + c.len_utf8()..];
                }
            }
            _ => {}
        }
    }
    ""
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn package_name_reads_the_declaration() {
        let cases = [
            ("package com.acme;\n\nclass Foo {}", Some("com.acme")),
            ("package com.acme.billing\n\nimport java.util.List", Some("com.acme.billing")),
            (
                "/*\n * Copyright (c) Acme. package com.wrong;\n */\n// package com.wrong\npackage com.acme;",
                Some("com.acme"),
            ),
            ("\u{feff}package com.acme;", Some("com.acme")),
            ("@file:JvmName(\"Utils\")\n\npackage com.acme.util", Some("com.acme.util")),
            ("@file:Suppress(\"a)b\", \"c\")\npackage com.acme", Some("com.acme")),
            ("@Deprecated\npackage com.acme.old;", Some("com.acme.old")),
            ("package com.acme // the billing package\n", Some("com.acme")),
            ("package com.acme.`fun`\n", Some("com.acme.fun")),
            ("import java.util.List;\n\nclass Foo {}", None),
            ("class packaged {}", None),
            ("", None),
        ];
        for (source, expected) in cases {
            assert_eq!(package_name(source).as_deref(), expected, "{source:?}");
        }
    }

    fn write(root: &Path, relative: &str, content: &str) {
        let path = root.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, content).unwrap();
    }

    #[test]
    fn sources_are_keyed_by_package_and_ambiguous_keys_are_dropped() {
        let repo = tempfile::tempdir().unwrap();
        let root = repo.path();
        // Kotlin does not require the folder to match the package.
        write(
            root,
            "app/src/main/kotlin/billing/Invoice.kt",
            "package com.acme.billing\n",
        );
        write(
            root,
            "app/src/main/java/com/acme/build/Tool.java",
            "package com.acme.build;\n",
        );
        // Two modules with the same class but different code: no frame can tell them apart.
        write(
            root,
            "a/src/main/java/com/acme/Clash.java",
            "package com.acme;\nclass Clash { int a; }\n",
        );
        write(
            root,
            "b/src/main/java/com/acme/Clash.java",
            "package com.acme;\nclass Clash { int b; }\n",
        );
        // Identical copies are not ambiguous.
        write(
            root,
            "a/src/main/java/com/acme/Same.java",
            "package com.acme;\nclass Same {}\n",
        );
        write(
            root,
            "b/src/main/java/com/acme/Same.java",
            "package com.acme;\nclass Same {}\n",
        );
        write(
            root,
            "app/src/test/java/com/acme/FooTest.java",
            "package com.acme;\n",
        );
        write(
            root,
            "app/build/generated/com/acme/Gen.java",
            "package com.acme;\n",
        );
        write(
            root,
            "app/target/classes/com/acme/Gen2.java",
            "package com.acme;\n",
        );
        write(root, ".git/hooks/Hook.java", "package com.acme;\n");
        write(
            root,
            "app/src/main/resources/notes.txt",
            "not a source file",
        );

        let sources = collect_sources(&[root.to_path_buf()]).unwrap();

        let keys: Vec<&str> = sources.keys().map(String::as_str).collect();
        assert_eq!(
            keys,
            [
                "com/acme/Same.java",
                "com/acme/billing/Invoice.kt",
                "com/acme/build/Tool.java",
            ]
        );
    }

    #[test]
    fn the_layout_around_the_root_decides_what_is_skipped() {
        let repo = tempfile::tempdir().unwrap();
        let root = repo.path();
        write(root, "app/build.gradle", "");
        write(
            root,
            "app/src/main/java/com/acme/build/Tool.java",
            "package com.acme.build;\nclass Tool {}\n",
        );
        write(
            root,
            "app/src/main/java/com/acme/test/Probe.java",
            "package com.acme.test;\n",
        );
        write(
            root,
            "app/src/test/java/com/acme/build/Tool.java",
            "package com.acme.build;\nclass Tool { boolean fake; }\n",
        );
        write(
            root,
            "app/build/generated/sources/annotationProcessor/java/main/com/acme/out/Gen.java",
            "package com.acme.out;\n",
        );

        let main = ["com/acme/build/Tool.java", "com/acme/test/Probe.java"];
        let cases: [(&str, &[&str]); 4] = [
            ("", &main),
            ("app/src", &main),
            ("app/src/main/java", &main),
            (
                "app/build/generated/sources/annotationProcessor/java/main",
                &["com/acme/out/Gen.java"],
            ),
        ];
        for (relative, expected) in cases {
            let sources = collect_sources(&[root.join(relative)]).unwrap();
            let keys: Vec<&str> = sources.keys().map(String::as_str).collect();
            assert_eq!(keys, expected, "root {relative:?}");
        }
    }

    #[test]
    fn bundle_id_does_not_depend_on_the_checkout_location() {
        let first = tempfile::tempdir().unwrap();
        let second = tempfile::tempdir().unwrap();
        for root in [first.path(), second.path()] {
            write(
                root,
                "src/main/java/com/acme/Foo.java",
                "package com.acme;\nclass Foo {}\n",
            );
        }

        let id = |root: &Path| {
            bundle_sources(collect_sources(&[root.to_path_buf()]).unwrap(), None)
                .unwrap()
                .id
        };
        assert_eq!(id(first.path()), id(second.path()));

        write(
            second.path(),
            "src/main/java/com/acme/Foo.java",
            "package com.acme;\nclass Foo { }\n",
        );
        assert_ne!(id(first.path()), id(second.path()));
    }

    #[test]
    fn unchanged_sources_get_a_new_id_in_a_new_release() {
        let sources = BTreeMap::from([(
            "com/acme/Foo.java".to_string(),
            "package com.acme;\nclass Foo {}\n".to_string(),
        )]);
        let id = |release: Option<&str>| bundle_sources(sources.clone(), release).unwrap().id;

        assert_eq!(id(Some("release-1")), id(Some("release-1")));
        assert_ne!(id(Some("release-1")), id(Some("release-2")));
        assert_ne!(id(None), id(Some("release-1")));
    }
}
