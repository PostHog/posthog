use std::io::Cursor;
use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use clap::Subcommand;
use posthog_symbol_data::{
    read_symbol_data, AppleDsym, HermesMap, ProguardMapping, SourceAndMap, SymbolDataError,
};
use tracing::info;

use crate::{api::symbol_sets, invocation_context::context};

#[derive(Subcommand)]
pub enum SymbolSetsSubcommand {
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

    let owned = data.to_vec();

    // Try each type — read_symbol_data returns InvalidDataType when the
    // header type field doesn't match, so we use that to fall through.
    if let Ok(parsed) = read_symbol_data::<SourceAndMap>(owned.clone()) {
        let source_path = output.join(format!("{base_name}.js"));
        fs::write(&source_path, &parsed.minified_source).context("Failed to write source file")?;
        info!("Wrote {}", source_path.display());

        let map_path = output.join(format!("{base_name}.js.map"));
        fs::write(&map_path, &parsed.sourcemap).context("Failed to write sourcemap file")?;
        info!("Wrote {}", map_path.display());

        println!("Extracted source and sourcemap to {}", output.display());
        return Ok(());
    }

    if let Ok(parsed) = read_symbol_data::<HermesMap>(owned.clone()) {
        let map_path = output.join(format!("{base_name}.hbc.map"));
        fs::write(&map_path, &parsed.sourcemap).context("Failed to write hermes sourcemap")?;
        info!("Wrote {}", map_path.display());

        println!("Extracted hermes sourcemap to {}", output.display());
        return Ok(());
    }

    if let Ok(parsed) = read_symbol_data::<ProguardMapping>(owned.clone()) {
        let map_path = output.join(format!("{base_name}.txt"));
        fs::write(&map_path, &parsed.content).context("Failed to write proguard mapping")?;
        info!("Wrote {}", map_path.display());

        println!("Extracted proguard mapping to {}", output.display());
        return Ok(());
    }

    match read_symbol_data::<AppleDsym>(owned) {
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
    use std::path::Component;

    let dsym_dir = output.join(base_name);
    fs::create_dir_all(&dsym_dir).context("Failed to create dSYM output directory")?;

    let reader = Cursor::new(zip_data);
    let mut archive = zip::ZipArchive::new(reader).context("Failed to read dSYM ZIP archive")?;

    for i in 0..archive.len() {
        let mut file = archive.by_index(i).context("Failed to read ZIP entry")?;

        // Sanitize: keep only Normal components, stripping .., ., and root prefixes
        let safe_name: PathBuf = std::path::Path::new(file.name())
            .components()
            .filter_map(|c| match c {
                Component::Normal(part) => Some(part),
                _ => None,
            })
            .collect();

        if safe_name.as_os_str().is_empty() {
            continue;
        }

        let out_path = dsym_dir.join(&safe_name);

        if let Some(parent) = out_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let mut out_file = fs::File::create(&out_path)
            .context(format!("Failed to create {}", out_path.display()))?;
        std::io::copy(&mut file, &mut out_file)?;
        info!("Wrote {}", out_path.display());
    }

    println!(
        "Extracted dSYM ({} files) to {}",
        archive.len(),
        dsym_dir.display()
    );
    Ok(())
}

/// Extract a reasonable base filename from the symbol set ref.
fn derive_base_name(ref_str: &str) -> String {
    let name = std::path::Path::new(ref_str)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(ref_str);
    let name = if name == ".." || name == "." {
        "symbol_set"
    } else {
        name
    };
    // Strip common extensions so we can re-add the correct ones
    let name = name
        .strip_suffix(".js.map")
        .or_else(|| name.strip_suffix(".hbc.map"))
        .or_else(|| name.strip_suffix(".map"))
        .or_else(|| name.strip_suffix(".js"))
        .or_else(|| name.strip_suffix(".txt"))
        .or_else(|| name.strip_suffix(".dSYM"))
        .unwrap_or(name);

    if name.is_empty() {
        "symbol_set".to_string()
    } else {
        name.to_string()
    }
}
