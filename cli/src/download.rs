use std::io::{Cursor, Read};
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

use anyhow::{Context, Result};
use clap::Subcommand;
use posthog_symbol_data::{
    read_symbol_data, AppleDsym, ElfDebugInfo, HermesMap, ProguardMapping, SourceAndMap,
    SymbolDataError,
};
use tracing::info;

use crate::{api::symbol_sets, invocation_context::context};

#[derive(Subcommand)]
pub enum SymbolSetsSubcommand {
    /// Upload native debug symbols from a directory. ELF executables, shared
    /// libraries, and `objcopy --only-keep-debug` companions with debug info are
    /// uploaded, as are Apple `.dSYM` bundles (macOS only — needs `dwarfdump`
    /// from Xcode); other files are reported and skipped.
    Upload(crate::debug_symbols::upload::Args),
    /// Download and extract a symbol set (sourcemap, hermes, proguard, or dSYM)
    Download(DownloadArgs),
    /// Extract a local symbol set binary file (decompress and split)
    Extract(ExtractArgs),
}

#[derive(clap::Args, Clone)]
pub struct DownloadArgs {
    /// Symbol set ID to download
    #[arg(long, required_unless_present = "ref")]
    pub id: Option<String>,

    /// Symbol set ref to download (looked up by ref)
    #[arg(long = "ref", required_unless_present = "id")]
    pub r#ref: Option<String>,

    /// Output directory for extracted files
    #[arg(short, long, default_value = ".")]
    pub output: PathBuf,
}

#[derive(clap::Args, Clone)]
pub struct ExtractArgs {
    /// Path to the symbol set binary file
    pub file: PathBuf,

    /// Output directory for extracted files
    #[arg(short, long, default_value = ".")]
    pub output: PathBuf,
}

pub fn download(args: &DownloadArgs) -> Result<()> {
    context().capture_command_invoked("symbolset_download");

    let (id, base_name) = match (&args.id, &args.r#ref) {
        (Some(id), _) => (id.clone(), id.clone()),
        (_, Some(r)) => {
            info!("Resolving ref: {r}");
            let id = symbol_sets::resolve_ref(r)?;
            let base_name = derive_base_name(r);
            (id, base_name)
        }
        _ => anyhow::bail!("Either --id or --ref must be provided"),
    };

    info!("Downloading symbol set {id}");
    let data = symbol_sets::download_bytes(&id)?;
    info!("Downloaded {} bytes", data.len());

    extract_symbol_data(&data, &base_name, &args.output)
}

pub fn extract(args: &ExtractArgs) -> Result<()> {
    let data =
        fs::read(&args.file).context(format!("Failed to read file {}", args.file.display()))?;
    info!("Read {} bytes from {}", data.len(), args.file.display());

    let base_name = derive_base_name(
        args.file
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("symbol_set"),
    );
    extract_symbol_data(&data, &base_name, &args.output)
}

fn extract_symbol_data(data: &[u8], base_name: &str, output: &Path) -> Result<()> {
    fs::create_dir_all(output).context("Failed to create output directory")?;

    // Try each type — read_symbol_data returns InvalidDataType when the
    // header type field doesn't match, so we use that to fall through.
    if let Ok(parsed) = read_symbol_data::<SourceAndMap>(data) {
        write_output_file(
            output,
            format!("{base_name}.js"),
            parsed.minified_source.as_bytes(),
        )
        .context("Failed to write source file")?;
        write_output_file(
            output,
            format!("{base_name}.js.map"),
            parsed.sourcemap.as_bytes(),
        )
        .context("Failed to write sourcemap file")?;

        crate::safe_println!("Extracted source and sourcemap to {}", output.display());
        return Ok(());
    }

    if let Ok(parsed) = read_symbol_data::<HermesMap>(data) {
        write_output_file(
            output,
            format!("{base_name}.hbc.map"),
            parsed.sourcemap.as_bytes(),
        )
        .context("Failed to write hermes sourcemap")?;

        crate::safe_println!("Extracted hermes sourcemap to {}", output.display());
        return Ok(());
    }

    if let Ok(parsed) = read_symbol_data::<ProguardMapping>(data) {
        write_output_file(
            output,
            format!("{base_name}.txt"),
            parsed.content.as_bytes(),
        )
        .context("Failed to write proguard mapping")?;

        crate::safe_println!("Extracted proguard mapping to {}", output.display());
        return Ok(());
    }

    if let Ok(parsed) = read_symbol_data::<ElfDebugInfo>(data) {
        // Same ZIP layout as dSYM uploads: the binary as `dwarf` at the root
        // plus an optional `__source/` bundle.
        extract_dsym_zip(&parsed.data, base_name, output)?;
        return Ok(());
    }

    match read_symbol_data::<AppleDsym>(data) {
        Ok(parsed) => {
            extract_dsym_zip(&parsed.data, base_name, output)?;
            Ok(())
        }
        Err(SymbolDataError::InvalidDataType(actual, _)) => {
            anyhow::bail!("Unknown symbol data type: {actual}")
        }
        Err(e) => {
            anyhow::bail!("Failed to parse symbol set: {e}")
        }
    }
}

/// Extract a dSYM ZIP archive (DWARF binary + optional source files).
fn extract_dsym_zip(zip_data: &[u8], base_name: &str, output: &Path) -> Result<()> {
    let dsym_dir = output.join(base_name);

    let reader = Cursor::new(zip_data);
    let mut archive = zip::ZipArchive::new(reader).context("Failed to read dSYM ZIP archive")?;

    for i in 0..archive.len() {
        let mut file = archive.by_index(i).context("Failed to read ZIP entry")?;

        // Sanitize: keep only Normal components, stripping .., ., and root prefixes.
        // On Windows a mid-path `C:` is Normal here but becomes a drive prefix
        // once pushed, which replaces the path, so each part is checked alone.
        let safe_name: PathBuf = std::path::Path::new(file.name())
            .components()
            .filter_map(|c| match c {
                Component::Normal(part) if is_plain_component(part) => Some(part),
                _ => None,
            })
            .collect();

        if safe_name.as_os_str().is_empty() {
            continue;
        }

        write_output_file(output, Path::new(base_name).join(&safe_name), &mut file)?;
    }

    crate::safe_println!(
        "Extracted dSYM ({} files) to {}",
        archive.len(),
        dsym_dir.display()
    );
    Ok(())
}

/// Writes `contents` to `output/relative`, creating missing directories.
/// An existing output directory can hold symlinks, and a write through one
/// lands outside it. So this refuses a symlink at `output` or below it.
/// Directories above `output` are the caller's choice and stay followed.
fn write_output_file(
    output: &Path,
    relative: impl AsRef<Path>,
    mut contents: impl Read,
) -> Result<()> {
    // Rebuilt from components so a trailing `/` or `/.` cannot make the
    // check below see through a symlinked `output`.
    let mut path: PathBuf = output.components().collect();
    let mut parts = relative.as_ref().components();
    loop {
        if path.is_symlink() {
            anyhow::bail!(
                "The CLI does not write through the symlink at {}. Use an output directory that is not a symlink and holds no symlinks.",
                path.display()
            );
        }
        let Some(part) = parts.next() else { break };
        path.push(part);
    }

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("Failed to create directory {}", parent.display()))?;
    }
    let mut file =
        fs::File::create(&path).with_context(|| format!("Failed to create {}", path.display()))?;
    std::io::copy(&mut contents, &mut file)?;
    info!("Wrote {}", path.display());
    Ok(())
}

/// Extract a reasonable base filename from the symbol set ref. Callers join
/// the result onto the output directory, so anything that is not a single
/// plain path component falls back to `symbol_set`.
fn derive_base_name(ref_str: &str) -> String {
    let name = std::path::Path::new(ref_str)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default();
    // Strip common extensions so we can re-add the correct ones
    let name = name
        .strip_suffix(".js.map")
        .or_else(|| name.strip_suffix(".hbc.map"))
        .or_else(|| name.strip_suffix(".map"))
        .or_else(|| name.strip_suffix(".js"))
        .or_else(|| name.strip_suffix(".txt"))
        .or_else(|| name.strip_suffix(".dSYM"))
        .unwrap_or(name);

    if is_plain_component(name) {
        name.to_string()
    } else {
        "symbol_set".to_string()
    }
}

fn is_plain_component(name: impl AsRef<Path>) -> bool {
    let name = name.as_ref();
    let mut components = name.components();
    // Windows trims trailing dots and spaces from each path part when it opens
    // a file, so a part that ends in one can open a different name than the one
    // checked here.
    let trimmed_on_windows = matches!(
        name.as_os_str().as_encoded_bytes().last(),
        Some(b'.' | b' ')
    );
    matches!(components.next(), Some(Component::Normal(_)))
        && components.next().is_none()
        && !trimmed_on_windows
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        io::{Cursor, Write},
    };

    use posthog_symbol_data::{write_symbol_data, AppleDsym};

    use super::{derive_base_name, extract, ExtractArgs};

    #[test]
    fn extract_keeps_dsym_files_inside_the_output_directory() {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        zip.start_file("dwarf", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"debug info").unwrap();
        zip.start_file("../../source.c", zip::write::SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"source").unwrap();
        let zip_data = zip.finish().unwrap().into_inner();

        let root = tempfile::tempdir().unwrap();
        let file = root.path().join("...dSYM");
        fs::write(
            &file,
            write_symbol_data(AppleDsym { data: zip_data }).unwrap(),
        )
        .unwrap();
        let output = root.path().join("out");

        extract(&ExtractArgs {
            file,
            output: output.clone(),
        })
        .unwrap();

        assert!(!root.path().join("dwarf").exists());
        assert!(!root.path().join("source.c").exists());
        assert!(output.join("symbol_set").join("dwarf").is_file());
        assert!(output.join("symbol_set").join("source.c").is_file());
    }

    fn dsym_artifact() -> Vec<u8> {
        let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
        for name in ["dwarf", "__source/app.c"] {
            zip.start_file(name, zip::write::SimpleFileOptions::default())
                .unwrap();
            zip.write_all(b"extracted").unwrap();
        }
        write_symbol_data(AppleDsym {
            data: zip.finish().unwrap().into_inner(),
        })
        .unwrap()
    }

    #[cfg(unix)]
    #[test]
    fn extract_does_not_write_through_symlinks_in_the_output_directory() {
        use posthog_symbol_data::SourceAndMap;

        let dsym = ("bundle.dSYM", dsym_artifact());
        let sourcemap = (
            "bundle.js.map",
            write_symbol_data(SourceAndMap {
                minified_source: "extracted".to_string(),
                sourcemap: "extracted".to_string(),
            })
            .unwrap(),
        );

        // (symlink under the temp root, its target, output directory, artifact)
        let cases = [
            ("out", "outside", "out", &dsym),
            ("out", "outside", "out/", &dsym),
            ("out", "outside", "out/.", &dsym),
            ("out/bundle", "outside", "out", &dsym),
            ("out/bundle/__source", "outside", "out", &dsym),
            ("out/bundle/dwarf", "outside/existing.txt", "out", &dsym),
            (
                "out/bundle.js.map",
                "outside/existing.txt",
                "out",
                &sourcemap,
            ),
        ];

        for (link, target, output, (artifact_name, artifact)) in cases {
            let root = tempfile::tempdir().unwrap();
            let outside = root.path().join("outside");
            fs::create_dir(&outside).unwrap();
            fs::write(outside.join("existing.txt"), "original").unwrap();
            let link_path = root.path().join(link);
            fs::create_dir_all(link_path.parent().unwrap()).unwrap();
            std::os::unix::fs::symlink(root.path().join(target), &link_path).unwrap();
            let file = root.path().join(artifact_name);
            fs::write(&file, artifact).unwrap();

            let result = extract(&ExtractArgs {
                file,
                output: root.path().join(output),
            });

            assert!(result.is_err(), "{link} {output}");
            let outside_files: Vec<_> = fs::read_dir(&outside)
                .unwrap()
                .map(|entry| entry.unwrap().file_name())
                .collect();
            assert_eq!(outside_files, ["existing.txt"], "{link} {output}");
            assert_eq!(
                fs::read_to_string(outside.join("existing.txt")).unwrap(),
                "original",
                "{link} {output}"
            );
        }

        let root = tempfile::tempdir().unwrap();
        let real = root.path().join("real");
        fs::create_dir(&real).unwrap();
        std::os::unix::fs::symlink(&real, root.path().join("link")).unwrap();
        let file = root.path().join(dsym.0);
        fs::write(&file, &dsym.1).unwrap();

        extract(&ExtractArgs {
            file,
            output: root.path().join("link").join("out"),
        })
        .unwrap();

        assert!(real.join("out").join("bundle").join("dwarf").is_file());
    }

    #[test]
    fn extract_overwrites_files_from_an_earlier_extraction() {
        let root = tempfile::tempdir().unwrap();
        let file = root.path().join("bundle.dSYM");
        fs::write(&file, dsym_artifact()).unwrap();
        let args = ExtractArgs {
            file,
            output: root.path().join("out"),
        };

        extract(&args).unwrap();
        let dwarf = args.output.join("bundle").join("dwarf");
        fs::write(&dwarf, "stale content from an earlier extraction").unwrap();
        extract(&args).unwrap();

        assert_eq!(fs::read_to_string(&dwarf).unwrap(), "extracted");
    }

    #[test]
    fn derive_base_name_falls_back_to_symbol_set() {
        assert_eq!(
            derive_base_name("https://example.com/static/app.js.map"),
            "app"
        );
        assert_eq!(derive_base_name("../../../"), "symbol_set");
        assert_eq!(derive_base_name("/"), "symbol_set");
        assert_eq!(derive_base_name(".. "), "symbol_set");
        assert_eq!(derive_base_name("app.."), "symbol_set");
    }
}
