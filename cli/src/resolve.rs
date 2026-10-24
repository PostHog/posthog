//! Resolve one frame against an uploaded symbol set, downloaded by ref or read from a file.
//! This does not reproduce Cymbal's selection of the set for an exception.
use std::{
    fs,
    io::{self, Cursor, Read},
    path::PathBuf,
};

use anyhow::{bail, Context, Result};
use clap::Args;
use posthog_symbol_data::{
    read_symbol_data, AppleDsym, ElfDebugInfo, HermesMap, ProguardMapping, SourceAndMap,
};
use serde::Deserialize;
use serde_json::{json, Value};
use symbolic::{
    debuginfo::Archive,
    demangle::{Demangle, DemangleOptions},
    symcache::{SymCache, SymCacheConverter},
};

#[derive(Args)]
pub struct ResolveArgs {
    /// Uploaded symbol-set binary. When provided, use these bytes instead of downloading by ref.
    pub file: Option<PathBuf>,
    /// Symbol-set ref (chunk ID, map ID or debug ID). Required when downloading; optional for a local file.
    #[arg(long, required_unless_present = "file")]
    pub r#ref: Option<String>,
    /// A raw exception frame as JSON (platform: node:javascript, web:javascript, java, hermes, apple, native)
    #[arg(
        long,
        conflicts_with = "frame_file",
        required_unless_present = "frame_file"
    )]
    pub frame: Option<String>,
    /// Read a raw exception frame from a JSON file, or use - for stdin
    #[arg(long, conflicts_with = "frame", required_unless_present = "frame")]
    pub frame_file: Option<PathBuf>,
    /// The matching entry from the event's $debug_images, as JSON (required for apple/native)
    #[arg(long)]
    pub debug_image: Option<String>,
}

fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .with_context(|| format!("missing {key}"))
}

fn frame_ref<'a>(frame: &'a Value, platform: &str, image: Option<&'a Value>) -> Result<&'a str> {
    match platform {
        "node:javascript" | "web:javascript" | "hermes" => frame
            .get("chunk_id")
            .or_else(|| frame.get("chunkId"))
            .and_then(Value::as_str)
            .context("frame has no chunk_id"),
        "java" => Ok(field(frame, "map_id")?),
        "apple" | "native" => Ok(field(
            image.context("--debug-image is required")?,
            "debug_id",
        )?),
        _ => bail!("unsupported frame platform: {platform}"),
    }
}

fn generated_column(frame: &Value) -> Result<u32> {
    frame
        .get("colno")
        .and_then(Value::as_u64)
        .context("missing colno")?
        .try_into()
        .context("colno is out of range")
}

fn verify_js_map(map: &str, minified_source: &str, frame: &Value) -> Result<Value> {
    let line = frame
        .get("lineno")
        .and_then(Value::as_u64)
        .context("missing lineno")?
        .checked_sub(1)
        .context("lineno must be >= 1")?
        .try_into()
        .context("lineno is out of range")?;
    let column = generated_column(frame)?;
    let decoded = sourcemap::decode_slice(map.as_bytes()).context("invalid source map")?;
    let decoded = match decoded {
        sourcemap::DecodedMap::Index(index) => sourcemap::DecodedMap::Regular(
            index.flatten().context("flattening indexed source map")?,
        ),
        other => other,
    };
    let token = decoded
        .lookup_token(line, column)
        .filter(|token| token.get_dst_line() == line)
        .context("no mapping for frame location")?;
    let source = token.get_source().context("mapping has no source")?;
    let source_view = sourcemap::SourceView::new(minified_source.into());
    // A token name can be a local variable rather than the enclosing function.
    let function = frame
        .get("function")
        .and_then(Value::as_str)
        .and_then(|name| {
            decoded.get_original_function_name(line, column, Some(name), Some(&source_view))
        });
    Ok(json!({"source": source, "line": token.get_src_line() + 1,
        "column": token.get_src_col(), "function": function,
        "hasContent": token.get_source_view().is_some()}))
}

#[derive(Deserialize)]
struct HermesMapMetadata {
    #[serde(default, deserialize_with = "marker_present")]
    x_hermes_function_offsets: bool,
}

fn marker_present<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<bool, D::Error> {
    serde::de::IgnoredAny::deserialize(deserializer)?;
    Ok(true)
}

fn has_hermes_function_offsets(map: &str) -> Result<bool> {
    let map = match map.as_bytes().first() {
        Some(b')' | b']' | b'}' | b'\'') => {
            map.split_once('\n').map(|(_, map)| map).unwrap_or_default()
        }
        _ => map,
    };
    let metadata: HermesMapMetadata =
        serde_json::from_str(map).context("invalid Hermes metadata")?;
    Ok(metadata.x_hermes_function_offsets)
}

fn verify_hermes_map(map: &str, frame: &Value) -> Result<Value> {
    let decoded = sourcemap::decode_slice(map.as_bytes()).context("invalid Hermes source map")?;
    match &decoded {
        sourcemap::DecodedMap::Hermes(_) => {}
        sourcemap::DecodedMap::Regular(_) if has_hermes_function_offsets(map)? => {}
        _ => bail!("map has no Hermes bytecode offsets"),
    }
    let column = generated_column(frame)?;
    let token = decoded
        .lookup_token(0, column)
        .context("no mapping for frame location")?;
    let source = token.get_source().context("mapping has no source")?;
    let function = match &decoded {
        sourcemap::DecodedMap::Hermes(map) => map.get_original_function_name(column),
        _ => None,
    };
    Ok(json!({"source": source, "line": token.get_src_line() + 1,
        "column": token.get_src_col(), "function": function,
        "hasContent": token.get_source_view().is_some()}))
}

fn verify_proguard(map: &str, frame: &Value) -> Result<Value> {
    let mapping = proguard::ProguardMapping::new(map.as_bytes());
    if !mapping.is_valid() {
        bail!("invalid ProGuard mapping");
    }
    let mut bytes = Vec::new();
    proguard::ProguardCache::write(&mapping, &mut bytes).context("building ProGuard cache")?;
    let cache = proguard::ProguardCache::parse(&bytes).context("reading ProGuard cache")?;
    let module = field(frame, "module")?;
    let function = field(frame, "function")?;
    let line = frame.get("lineno").and_then(Value::as_u64).unwrap_or(0) as usize;
    let stack = if let Some(file) = frame.get("filename").and_then(Value::as_str) {
        proguard::StackFrame::with_file(module, function, line, file)
    } else {
        proguard::StackFrame::new(module, function, line)
    };
    let frames: Vec<_> = cache
        .remap_frame(&stack)
        .map(|f| {
            json!({
                "source": f.file(), "line": f.line(), "module": f.class(), "function": f.method()
            })
        })
        .collect();
    if frames.is_empty() {
        bail!("no original frames in ProGuard mapping");
    }
    Ok(json!({"frames": frames}))
}

fn display_name(name: symbolic::common::Name<'_>) -> String {
    name.demangle(DemangleOptions::name_only())
        .unwrap_or_else(|| name.to_string())
}

fn lookup_address(offset: u64) -> u64 {
    offset.saturating_sub(1)
}

fn hex(value: &str) -> Result<u64> {
    u64::from_str_radix(value.trim_start_matches("0x").trim_start_matches("0X"), 16)
        .with_context(|| format!("invalid address: {value}"))
}

const MAX_NATIVE_DEBUG_BYTES: u64 = 512 * 1024 * 1024;

fn read_bounded<R: Read>(reader: R, declared_size: u64, limit: u64) -> Result<Vec<u8>> {
    if declared_size > limit {
        bail!("DWARF entry exceeds the {limit}-byte limit");
    }
    let mut binary = Vec::new();
    reader
        .take(limit + 1)
        .read_to_end(&mut binary)
        .context("decompressing DWARF entry")?;
    if binary.len() as u64 > limit {
        bail!("DWARF entry exceeds the {limit}-byte limit");
    }
    Ok(binary)
}

fn native_bundle(data: &[u8], apple: bool) -> Result<Vec<u8>> {
    if apple {
        return read_symbol_data::<AppleDsym>(data)
            .map(|set| set.data)
            .context("expected a dSYM symbol set");
    }
    let elf_error = match read_symbol_data::<ElfDebugInfo>(data) {
        Ok(set) => return Ok(set.data),
        Err(error) => error,
    };
    read_symbol_data::<AppleDsym>(data)
        .map(|set| set.data)
        .with_context(|| format!("expected an ELF or dSYM symbol set (ELF decode: {elf_error})"))
}

fn find_native_object<'d>(
    archive: &Archive<'d>,
    expected_id: &str,
) -> Result<symbolic::debuginfo::Object<'d>> {
    let mut parse_error = None;
    for candidate in archive.objects() {
        match candidate {
            Ok(candidate)
                if candidate
                    .debug_id()
                    .to_string()
                    .eq_ignore_ascii_case(expected_id) =>
            {
                return Ok(candidate);
            }
            Ok(_) => {}
            Err(err) if parse_error.is_none() => parse_error = Some(err),
            Err(_) => {}
        }
    }
    if let Some(err) = parse_error {
        return Err(err).context("parsing native object");
    }
    bail!("symbol bundle has no object matching the frame's debug ID");
}

fn verify_native(
    zip_data: &[u8],
    frame: &Value,
    image: &Value,
    expected_id: &str,
) -> Result<Value> {
    let mut zip =
        zip::ZipArchive::new(Cursor::new(zip_data)).context("invalid symbol bundle ZIP")?;
    let name = if zip.file_names().any(|name| name == "dwarf") {
        "dwarf".to_string()
    } else {
        zip.file_names()
            .find(|name| name.contains("/Contents/Resources/DWARF/") && !name.ends_with('/'))
            .context("no DWARF file in symbol bundle")?
            .to_string()
    };
    let file = zip.by_name(&name).context("opening DWARF entry")?;
    let declared_size = file.size();
    let binary = read_bounded(file, declared_size, MAX_NATIVE_DEBUG_BYTES)?;
    let archive = Archive::parse(&binary).context("invalid debug information")?;
    // Prefer the slice identified by the exception's debug image, rather than the first
    // slice in a universal dSYM (which may be for a different architecture).
    let object = find_native_object(&archive, expected_id)?;
    let mut converter = SymCacheConverter::new();
    converter
        .process_object(&object)
        .context("building symcache")?;
    let mut cache_bytes = Vec::new();
    converter
        .serialize(&mut Cursor::new(&mut cache_bytes))
        .context("serializing symcache")?;
    let cache = SymCache::parse(&cache_bytes).context("reading symcache")?;
    let base = hex(field(image, "image_addr")?)?;
    if let Some(uuid) = frame.get("image_uuid").and_then(Value::as_str) {
        if !uuid.eq_ignore_ascii_case(expected_id) {
            bail!("frame image_uuid does not match debug image");
        }
    }
    if let Some(frame_base) = frame.get("image_addr").and_then(Value::as_str) {
        if hex(frame_base)? != base {
            bail!("frame image_addr does not match debug image");
        }
    }
    let instruction = hex(field(frame, "instruction_addr")?)?;
    let offset = instruction
        .checked_sub(base)
        .context("instruction is before image base")?;
    // Both Apple and native return addresses point after the call site.
    let lookup = lookup_address(offset);
    let frames: Vec<_> = cache
        .lookup(lookup)
        .map(|f| {
            json!({
                "source": f.file().map(|file| file.full_path()), "line": f.line(),
                "function": display_name(f.function().name_for_demangling())
            })
        })
        .collect();
    if frames.is_empty() {
        bail!("no symbols for instruction address");
    }
    Ok(json!({"frames": frames}))
}

// Keep the CLI's output shape independent of the artifact type. ProGuard and
// native addresses may expand into several frames; JS/Hermes still return one.
// null means the field is unavailable for that format (not `false`).
fn render_frames(result: Value) -> Value {
    let frames = result
        .get("frames")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_else(|| vec![result]);
    json!({"frames": frames.iter().map(|frame| json!({
        "source": frame.get("source"),
        "line": frame.get("line"),
        "column": frame.get("column"),
        "function": frame.get("function"),
        "module": frame.get("module"),
        "hasContent": frame.get("hasContent"),
    })).collect::<Vec<_>>()})
}

fn read_frame(args: &ResolveArgs) -> Result<Value> {
    let input = if let Some(path) = &args.frame_file {
        if path.as_os_str() == "-" {
            let mut input = String::new();
            io::stdin()
                .read_to_string(&mut input)
                .context("reading frame from stdin")?;
            input
        } else {
            fs::read_to_string(path)
                .with_context(|| format!("reading frame from {}", path.display()))?
        }
    } else {
        args.frame
            .clone()
            .context("provide --frame or --frame-file")?
    };
    serde_json::from_str(&input).context("invalid frame JSON")
}

fn load_symbol_set_with(
    file: Option<&PathBuf>,
    r#ref: &str,
    resolve_ref: impl FnOnce(&str) -> Result<String>,
    download_bytes: impl FnOnce(&str) -> Result<Vec<u8>>,
) -> Result<Vec<u8>> {
    if let Some(file) = file {
        return fs::read(file)
            .with_context(|| format!("reading uploaded symbol set from {}", file.display()));
    }
    let id =
        resolve_ref(r#ref).with_context(|| format!("looking up symbol set ref {:?}", r#ref))?;
    download_bytes(&id).with_context(|| format!("downloading symbol set {id}"))
}

fn resolve_frames(args: &ResolveArgs) -> Result<Value> {
    let frame = read_frame(args)?;
    let image: Option<Value> = args
        .debug_image
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .context("invalid --debug-image JSON")?;
    let platform = field(&frame, "platform")?;
    let selected = frame_ref(&frame, platform, image.as_ref())?;
    if let Some(expected) = args.r#ref.as_deref() {
        if selected != expected {
            bail!("frame ref {selected:?} does not match requested set {expected:?}");
        }
    }
    let data = load_symbol_set_with(
        args.file.as_ref(),
        args.r#ref.as_deref().unwrap_or(selected),
        crate::api::symbol_sets::resolve_ref,
        crate::api::symbol_sets::download_bytes,
    )?;
    let result = match platform {
        "node:javascript" | "web:javascript" => {
            let parsed: SourceAndMap =
                read_symbol_data(&data).context("expected a source-and-map symbol set")?;
            verify_js_map(&parsed.sourcemap, &parsed.minified_source, &frame)?
        }
        "hermes" => {
            let parsed: HermesMap =
                read_symbol_data(&data).context("expected a Hermes symbol set")?;
            verify_hermes_map(&parsed.sourcemap, &frame)?
        }
        "java" => {
            let parsed: ProguardMapping =
                read_symbol_data(&data).context("expected a ProGuard symbol set")?;
            verify_proguard(&parsed.content, &frame)?
        }
        "apple" | "native" => {
            let image = image.as_ref().context("missing debug image")?;
            let bundle = native_bundle(&data, platform == "apple")?;
            verify_native(&bundle, &frame, image, selected)?
        }
        _ => bail!("unsupported platform: {platform}"),
    };
    Ok(render_frames(result))
}

pub fn resolve(args: &ResolveArgs) -> Result<()> {
    crate::safe_println!("{}", resolve_frames(args)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use posthog_symbol_data::write_symbol_data;

    #[test]
    fn local_file_uses_frame_ref_when_flag_is_absent() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("symbol-set.bin");
        let data = write_symbol_data(SourceAndMap {
            minified_source: "throw Error();".into(),
            sourcemap: r#"{"version":3,"sources":["src/boom.js"],"names":[],"mappings":"AAAA"}"#
                .into(),
        })
        .unwrap();
        fs::write(&file, data).unwrap();
        let args = ResolveArgs {
            file: Some(file),
            r#ref: None,
            frame: Some(
                r#"{"platform":"node:javascript","chunk_id":"chunk-1","lineno":1,"colno":0}"#
                    .into(),
            ),
            frame_file: None,
            debug_image: None,
        };
        assert_eq!(
            resolve_frames(&args).unwrap()["frames"][0]["source"],
            "src/boom.js"
        );
        let args = ResolveArgs {
            r#ref: Some("other-chunk".into()),
            ..args
        };
        assert!(resolve_frames(&args)
            .unwrap_err()
            .to_string()
            .contains("does not match requested set"));
    }

    #[test]
    fn local_file_skips_lookup_and_download() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("symbol-set.bin");
        fs::write(&file, [1, 2, 3]).unwrap();
        let bytes = load_symbol_set_with(
            Some(&file),
            "chunk-1",
            |_| panic!("local file should not trigger lookup"),
            |_| panic!("local file should not trigger download"),
        )
        .unwrap();
        assert_eq!(bytes, [1, 2, 3]);

        fs::remove_file(&file).unwrap();
        let error = load_symbol_set_with(
            Some(&file),
            "chunk-1",
            |_| panic!("local file should not trigger lookup"),
            |_| panic!("local file should not trigger download"),
        )
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("reading uploaded symbol set from"));
    }

    #[test]
    fn remote_bytes_are_looked_up_by_ref_then_downloaded() {
        let bytes = load_symbol_set_with(
            None,
            "chunk-1",
            |r| {
                assert_eq!(r, "chunk-1");
                Ok("set-id".into())
            },
            |id| {
                assert_eq!(id, "set-id");
                Ok(vec![4, 5])
            },
        )
        .unwrap();
        assert_eq!(bytes, [4, 5]);
        let lookup_error = load_symbol_set_with(
            None,
            "chunk-1",
            |_| anyhow::bail!("not found"),
            |_| panic!("download should not run after lookup failure"),
        )
        .unwrap_err();
        assert!(lookup_error
            .to_string()
            .contains("looking up symbol set ref"));
        let error = load_symbol_set_with(
            None,
            "chunk-1",
            |_| Ok("set-id".into()),
            |_| anyhow::bail!("not available"),
        )
        .unwrap_err();
        assert!(error.to_string().contains("downloading symbol set set-id"));
    }

    #[test]
    fn reads_a_frame_file_and_reports_invalid_json() {
        let dir = tempfile::tempdir().unwrap();
        let frame_file = dir.path().join("frame.json");
        fs::write(
            &frame_file,
            r#"{"platform":"node:javascript","chunk_id":"chunk-1"}"#,
        )
        .unwrap();
        let args = ResolveArgs {
            file: None,
            r#ref: Some("chunk-1".into()),
            frame: None,
            frame_file: Some(frame_file.clone()),
            debug_image: None,
        };
        assert_eq!(read_frame(&args).unwrap()["chunk_id"], "chunk-1");
        fs::write(&frame_file, "not json").unwrap();
        assert!(read_frame(&args)
            .unwrap_err()
            .to_string()
            .contains("invalid frame JSON"));
    }

    #[test]
    fn every_format_renders_the_same_frame_fields() {
        let js = render_frames(
            json!({"source":"src/app.js","line":3,"column":2,"function":null,"hasContent":true}),
        );
        let java = render_frames(
            json!({"frames":[{"source":"App.java","line":5,"module":"example.App","function":"run"}]}),
        );
        let native =
            render_frames(json!({"frames":[{"source":"App.swift","line":8,"function":"run"}]}));
        let expected = [
            "column",
            "function",
            "hasContent",
            "line",
            "module",
            "source",
        ];
        for output in [&js, &java, &native] {
            assert_eq!(output["frames"].as_array().unwrap().len(), 1);
            let keys: Vec<_> = output["frames"][0]
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect();
            assert_eq!(keys, expected);
        }
        assert_eq!(js["frames"][0]["hasContent"], true);
        assert!(java["frames"][0]["hasContent"].is_null());
        assert!(native["frames"][0]["column"].is_null());
    }

    #[test]
    fn resolves_uploaded_js_map_and_rejects_wrong_ref() {
        let map = r#"{"version":3,"file":"bundle.js","sources":["src/boom.js"],"sourcesContent":["throw Error();"],"names":[],"mappings":"AAAA"}"#;
        let data = write_symbol_data(SourceAndMap {
            minified_source: "throw Error();".into(),
            sourcemap: map.into(),
        })
        .unwrap();
        let parsed: SourceAndMap = read_symbol_data(&data).unwrap();
        let frame = json!({"platform":"node:javascript","chunk_id":"chunk-1","lineno":1,"colno":0});
        assert_eq!(
            frame_ref(&frame, "node:javascript", None).unwrap(),
            "chunk-1"
        );
        let result = verify_js_map(&parsed.sourcemap, &parsed.minified_source, &frame).unwrap();
        assert_eq!(result["source"], "src/boom.js");
        assert_eq!(result["line"], 1);
        let missing = verify_js_map(
            &parsed.sourcemap,
            &parsed.minified_source,
            &json!({"lineno":2,"colno":0}),
        )
        .unwrap_err();
        assert!(missing
            .to_string()
            .contains("no mapping for frame location"));
        assert!(verify_js_map(
            &parsed.sourcemap,
            &parsed.minified_source,
            &json!({"lineno":0,"colno":0})
        )
        .is_err());
    }

    #[test]
    fn indexed_js_map_respects_section_line_offset() {
        let map = r#"{"version":3,"sections":[{"offset":{"line":1,"column":0},"map":{"version":3,"sources":["src/app.js"],"names":[],"mappings":"AAAA"}}]}"#;
        let frame = json!({"lineno":2,"colno":0});
        assert_eq!(
            verify_js_map(map, "", &frame).unwrap()["source"],
            "src/app.js"
        );
        assert!(verify_js_map(map, "", &json!({"lineno":3,"colno":0})).is_err());
    }

    #[test]
    fn js_function_name_comes_from_enclosing_scope_not_variable_token() {
        let minified = "function a(){return b;}";
        for token_name in [Some("localVariable"), None] {
            let mut builder = sourcemap::SourceMapBuilder::new(Some("bundle.js"));
            builder.add(0, 0, 0, 0, Some("src/app.js"), Some("function"), false);
            builder.add(
                0,
                9,
                0,
                9,
                Some("src/app.js"),
                Some("originalFunction"),
                false,
            );
            builder.add(0, 20, 0, 25, Some("src/app.js"), token_name, false);
            let mut bytes = Vec::new();
            builder.into_sourcemap().to_writer(&mut bytes).unwrap();
            let map = String::from_utf8(bytes).unwrap();
            let frame = json!({"lineno":1,"colno":20,"function":"a"});
            let result = verify_js_map(&map, minified, &frame).unwrap();
            assert_eq!(
                result["function"], "originalFunction",
                "token name: {token_name:?}"
            );
        }
    }

    #[test]
    fn hermes_scope_name_is_not_the_token_name() {
        let map = r#"{"version":3,"sources":["src/app.js"],"names":["localVariable"],"mappings":"AAAAA","x_facebook_sources":[[{"names":["originalFunction"],"mappings":"AAA"}]]}"#;
        let frame = json!({"colno":0});
        assert_eq!(
            verify_hermes_map(map, &frame).unwrap()["function"],
            "originalFunction"
        );
    }

    #[test]
    fn hermes_map_requires_bytecode_offset_marker() {
        let map = r#"{"version":3,"sources":["src/app.js"],"names":[],"mappings":"AAAA","x_hermes_function_offsets":{}}"#;
        let frame = json!({"platform":"hermes","chunkId":"chunk-1","colno":0});
        let result = verify_hermes_map(map, &frame).unwrap();
        assert_eq!(result["source"], "src/app.js");
        assert!(result["function"].is_null());
        assert!(has_hermes_function_offsets(map).unwrap());
        assert!(has_hermes_function_offsets(&format!(")]}}'\n{map}")).unwrap());
        assert!(!has_hermes_function_offsets(
            r#"{"version":3,"sourcesContent":["large payload"]}"#
        )
        .unwrap());
        assert!(verify_hermes_map(
            r#"{"version":3,"sources":["src/app.js"],"names":[],"mappings":"AAAA"}"#,
            &frame,
        )
        .is_err());
    }

    #[test]
    fn native_accepts_dsym_or_elf_but_apple_requires_dsym() {
        let dsym = write_symbol_data(AppleDsym {
            data: vec![1, 2, 3],
        })
        .unwrap();
        let elf = write_symbol_data(ElfDebugInfo { data: vec![4, 5] }).unwrap();
        assert_eq!(native_bundle(&dsym, false).unwrap(), [1, 2, 3]);
        assert_eq!(native_bundle(&dsym, true).unwrap(), [1, 2, 3]);
        assert_eq!(native_bundle(&elf, false).unwrap(), [4, 5]);
        assert!(native_bundle(&elf, true).is_err());
    }

    #[test]
    fn native_debug_entry_is_bounded_even_with_incorrect_size_header() {
        assert_eq!(
            read_bounded(Cursor::new([1, 2, 3]), 3, 3).unwrap(),
            [1, 2, 3]
        );
        assert!(read_bounded(Cursor::new([1, 2, 3]), 3, 2).is_err());
        assert!(read_bounded(Cursor::new([1, 2, 3]), 2, 2).is_err());
    }

    #[test]
    fn invalid_native_object_reports_parse_failure_not_debug_id_mismatch() {
        let mut binary = [0; 16];
        binary[..4].copy_from_slice(b"\x7fELF");
        let archive = Archive::parse(&binary).unwrap();
        assert!(archive.objects().next().unwrap().is_err());
        let error = find_native_object(&archive, "unknown").unwrap_err();
        assert!(error.to_string().contains("parsing native object"));
    }

    #[test]
    fn native_return_address_and_function_name_match_cymbal() {
        assert_eq!(lookup_address(0), 0);
        assert_eq!(lookup_address(0x101), 0x100);
        assert_eq!(
            display_name(symbolic::common::Name::from("_ZN3foo3barEv")),
            "foo::bar"
        );
        assert_eq!(
            display_name(symbolic::common::Name::from("plain_function")),
            "plain_function"
        );
    }

    #[test]
    fn resolves_uploaded_proguard_mapping() {
        let map = "com.example.Original -> a.b:\n    1:1:void crash():17:17 -> c\n";
        let data = write_symbol_data(ProguardMapping {
            content: map.into(),
        })
        .unwrap();
        let parsed: ProguardMapping = read_symbol_data(&data).unwrap();
        let frame = json!({"platform":"java","map_id":"release-1","module":"a.b","function":"c","lineno":1,"filename":"SourceFile"});
        assert_eq!(frame_ref(&frame, "java", None).unwrap(), "release-1");
        let result = verify_proguard(&parsed.content, &frame).unwrap();
        assert_eq!(result["frames"][0]["module"], "com.example.Original");
        assert_eq!(result["frames"][0]["line"], 17);
    }
}
