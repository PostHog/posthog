//! Resolve one frame against a symbol set downloaded by ref.
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
use serde_json::{json, Value};
use symbolic::{
    debuginfo::Archive,
    symcache::{SymCache, SymCacheConverter},
};

#[derive(Args)]
pub struct ResolveArgs {
    /// Symbol-set ref selected by the exception's frame (chunk ID, map ID or debug ID)
    #[arg(long)]
    pub r#ref: String,
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

fn verify_map(map: &str, frame: &Value, hermes: bool) -> Result<Value> {
    let decoded = sourcemap::decode_slice(map.as_bytes()).context("invalid source map")?;
    if hermes && !matches!(decoded, sourcemap::DecodedMap::Hermes(_)) {
        // Hermes maps without Metro scope data decode as regular maps. They must still
        // carry the Hermes bytecode-offset marker, as Cymbal's parser requires.
        let metadata: Value = serde_json::from_str(map).context("invalid Hermes metadata")?;
        if metadata.get("x_hermes_function_offsets").is_none() {
            bail!("map has no Hermes bytecode offsets");
        }
    }
    let line = if hermes {
        0
    } else {
        frame
            .get("lineno")
            .and_then(Value::as_u64)
            .context("missing lineno")?
            .checked_sub(1)
            .context("lineno must be >= 1")?
            .try_into()
            .context("lineno is out of range")?
    };
    // Cymbal uses the SDK's column directly; only the line is 1-based.
    let col: u32 = frame
        .get("colno")
        .and_then(Value::as_u64)
        .context("missing colno")?
        .try_into()
        .context("colno is out of range")?;
    let token = decoded
        .lookup_token(line, col)
        .context("no mapping for frame location")?;
    let source = token.get_source().context("mapping has no source")?;
    Ok(json!({"source": source, "line": token.get_src_line() + 1,
        "column": token.get_src_col(), "function": token.get_name(),
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

fn hex(value: &str) -> Result<u64> {
    u64::from_str_radix(value.trim_start_matches("0x").trim_start_matches("0X"), 16)
        .with_context(|| format!("invalid address: {value}"))
}

fn verify_native(
    zip_data: &[u8],
    frame: &Value,
    image: &Value,
    expected_id: &str,
    apple: bool,
) -> Result<Value> {
    let mut zip =
        zip::ZipArchive::new(Cursor::new(zip_data)).context("invalid symbol bundle ZIP")?;
    let mut binary = Vec::new();
    let name = if zip.file_names().any(|name| name == "dwarf") {
        "dwarf".to_string()
    } else {
        zip.file_names()
            .find(|name| name.contains("/Contents/Resources/DWARF/") && !name.ends_with('/'))
            .context("no DWARF file in symbol bundle")?
            .to_string()
    };
    zip.by_name(&name)?.read_to_end(&mut binary)?;
    let archive = Archive::parse(&binary).context("invalid debug information")?;
    // Prefer the slice identified by the exception's debug image, rather than the first
    // slice in a universal dSYM (which may be for a different architecture).
    let object = archive
        .objects()
        .filter_map(Result::ok)
        .find(|obj| obj.debug_id().to_string().eq_ignore_ascii_case(expected_id))
        .context("symbol bundle has no object matching the frame's debug ID")?;
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
    // Apple exception frames are return addresses; Cymbal subtracts one for the call site.
    let lookup = if apple {
        offset.saturating_sub(1)
    } else {
        offset
    };
    let frames: Vec<_> = cache
        .lookup(lookup)
        .map(|f| {
            json!({
                "source": f.file().map(|file| file.full_path()), "line": f.line(),
                "function": f.function().name_for_demangling().to_string()
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

fn download_symbol_set_with(
    r#ref: &str,
    resolve_ref: impl FnOnce(&str) -> Result<String>,
    download_bytes: impl FnOnce(&str) -> Result<Vec<u8>>,
) -> Result<Vec<u8>> {
    let id =
        resolve_ref(r#ref).with_context(|| format!("looking up symbol set ref {:?}", r#ref))?;
    download_bytes(&id).with_context(|| format!("downloading symbol set {id}"))
}

pub fn resolve(args: &ResolveArgs) -> Result<()> {
    let frame = read_frame(args)?;
    let image: Option<Value> = args
        .debug_image
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .context("invalid --debug-image JSON")?;
    let platform = field(&frame, "platform")?;
    let selected = frame_ref(&frame, platform, image.as_ref())?;
    if selected != args.r#ref {
        bail!(
            "frame ref {selected:?} does not match uploaded set {:?}",
            args.r#ref
        );
    }
    let data = download_symbol_set_with(
        &args.r#ref,
        crate::api::symbol_sets::resolve_ref,
        crate::api::symbol_sets::download_bytes,
    )?;
    let result = match platform {
        "node:javascript" | "web:javascript" => {
            let parsed: SourceAndMap =
                read_symbol_data(&data).context("expected a source-and-map symbol set")?;
            verify_map(&parsed.sourcemap, &frame, false)?
        }
        "hermes" => {
            let parsed: HermesMap =
                read_symbol_data(&data).context("expected a Hermes symbol set")?;
            verify_map(&parsed.sourcemap, &frame, true)?
        }
        "java" => {
            let parsed: ProguardMapping =
                read_symbol_data(&data).context("expected a ProGuard symbol set")?;
            verify_proguard(&parsed.content, &frame)?
        }
        "apple" | "native" => {
            let image = image.as_ref().context("missing debug image")?;
            if platform == "apple" {
                let parsed: AppleDsym =
                    read_symbol_data(&data).context("expected a dSYM symbol set")?;
                verify_native(&parsed.data, &frame, image, selected, true)?
            } else {
                let parsed: ElfDebugInfo =
                    read_symbol_data(&data).context("expected an ELF symbol set")?;
                verify_native(&parsed.data, &frame, image, selected, false)?
            }
        }
        _ => bail!("unsupported platform: {platform}"),
    };
    crate::safe_println!("{}", render_frames(result));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use posthog_symbol_data::write_symbol_data;

    #[test]
    fn remote_bytes_are_looked_up_by_ref_then_downloaded() {
        let bytes = download_symbol_set_with(
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
        let lookup_error = download_symbol_set_with(
            "chunk-1",
            |_| anyhow::bail!("not found"),
            |_| panic!("download should not run after lookup failure"),
        )
        .unwrap_err();
        assert!(lookup_error
            .to_string()
            .contains("looking up symbol set ref"));
        let error = download_symbol_set_with(
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
            r#ref: "chunk-1".into(),
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
        let result = verify_map(&parsed.sourcemap, &frame, false).unwrap();
        assert_eq!(result["source"], "src/boom.js");
        assert_eq!(result["line"], 1);
        assert!(verify_map(&parsed.sourcemap, &json!({"lineno":0,"colno":0}), false).is_err());
    }

    #[test]
    fn hermes_map_requires_bytecode_offset_marker() {
        let map = r#"{"version":3,"sources":["src/app.js"],"names":[],"mappings":"AAAA","x_hermes_function_offsets":{}}"#;
        let frame = json!({"platform":"hermes","chunkId":"chunk-1","colno":0});
        assert_eq!(
            verify_map(map, &frame, true).unwrap()["source"],
            "src/app.js"
        );
        assert!(verify_map(
            r#"{"version":3,"sources":["src/app.js"],"names":[],"mappings":"AAAA"}"#,
            &frame,
            true
        )
        .is_err());
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
