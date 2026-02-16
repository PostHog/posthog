use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    dsym::{find_dsym_bundles, DsymFile, PlistInfo},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory containing dSYM files to upload. This is typically $DWARF_DSYM_FOLDER_PATH
    /// when running from an Xcode build phase.
    #[arg(short, long)]
    pub directory: PathBuf,

    /// The bundle identifier (e.g., com.example.app).
    /// If not provided, will be extracted from dSYM Info.plist.
    #[arg(long)]
    pub project: Option<String>,

    /// The marketing version (e.g., 1.2.3, CFBundleShortVersionString).
    /// If not provided, will be extracted from dSYM Info.plist.
    #[arg(long)]
    pub version: Option<String>,

    /// The build number (e.g., 42, CFBundleVersion).
    /// If not provided, will be extracted from dSYM Info.plist.
    #[arg(long)]
    pub build: Option<String>,

    /// The main dSYM file name (e.g., MyApp.app.dSYM).
    /// Used to extract version info from the correct dSYM when multiple are present.
    /// This is typically $DWARF_DSYM_FILE_NAME in Xcode build phases.
    #[arg(long)]
    pub main_dsym: Option<String>,
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        directory,
        project,
        version,
        build,
        main_dsym,
    } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Path {} canonicalization failed: {}",
            directory.display(),
            e
        )
    })?;

    if !directory.is_dir() {
        anyhow::bail!("Path {} is not a directory", directory.display());
    }

    // Find all dSYM bundles
    let dsym_paths = find_dsym_bundles(&directory)?;

    if dsym_paths.is_empty() {
        info!("No dSYM bundles found in {}", directory.display());
        return Ok(());
    }

    info!("Found {} dSYM bundle(s)", dsym_paths.len());

    // Find the main dSYM to extract version info from
    // Priority: --main-dsym flag > first .app.dSYM > first dSYM
    let main_dsym_path = if let Some(main_name) = main_dsym {
        // Use the specified main dSYM
        dsym_paths
            .iter()
            .find(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy() == *main_name)
                    .unwrap_or(false)
            })
            .cloned()
    } else {
        // Try to find the app dSYM (not a framework)
        dsym_paths
            .iter()
            .find(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy().ends_with(".app.dSYM"))
                    .unwrap_or(false)
            })
            .cloned()
    }
    .or_else(|| dsym_paths.first().cloned());

    // Extract info from main dSYM's Info.plist as fallback
    let plist_info = main_dsym_path.as_ref().and_then(|p| {
        let plist_path = p.join("Contents/Info.plist");
        match PlistInfo::from_plist(&plist_path) {
            Ok(info) => {
                info!(
                    "Extracted plist info from {}: {:?}",
                    p.file_name().unwrap_or_default().to_string_lossy(),
                    info
                );
                Some(info)
            }
            Err(e) => {
                tracing::debug!("Could not extract plist info: {}", e);
                None
            }
        }
    });

    // Determine project, version, build - CLI args take precedence over plist
    let resolved_project = project.clone().or_else(|| {
        plist_info
            .as_ref()
            .and_then(|p| p.bundle_identifier.clone())
    });
    let resolved_version = version
        .clone()
        .or_else(|| plist_info.as_ref().and_then(|p| p.short_version.clone()));
    let resolved_build = build
        .clone()
        .or_else(|| plist_info.as_ref().and_then(|p| p.bundle_version.clone()));

    // Build full version string: "version+build" or just "version" or just "build"
    let full_version = match (&resolved_version, &resolved_build) {
        (Some(v), Some(b)) => Some(format!("{v}+{b}")),
        (Some(v), None) => Some(v.clone()),
        (None, Some(b)) => Some(b.clone()),
        (None, None) => None,
    };

    if let Some(ref proj) = resolved_project {
        info!("Project: {}", proj);
    }
    if let Some(ref ver) = full_version {
        info!("Version: {}", ver);
    }

    // Set up release info
    let mut release_builder = ReleaseBuilder::default();

    // Add git info as metadata if available (but don't use it for project/version)
    if let Ok(Some(git_info)) = get_git_info(Some(directory.clone())) {
        release_builder.with_git(git_info);
    }

    // Add plist info as apple metadata
    if let Some(ref info) = plist_info {
        let _ = release_builder.with_metadata("dsym_info", info);
    }

    if let Some(ref project) = resolved_project {
        release_builder.with_name(project);
    }
    if let Some(ref version) = full_version {
        release_builder.with_version(version);
    }

    let release = release_builder
        .can_create()
        .then(|| release_builder.fetch_or_create())
        .transpose()?;

    let release_id = release.map(|r| r.id.to_string());

    // Process each dSYM
    let mut uploads: Vec<SymbolSetUpload> = Vec::new();

    for dsym_path in dsym_paths {
        info!("Processing dSYM: {}", dsym_path.display());

        match DsymFile::new(&dsym_path) {
            Ok(mut dsym_file) => {
                dsym_file.release_id = release_id.clone();
                info!(
                    "  UUIDs: {} ({})",
                    dsym_file.uuids.join(", "),
                    dsym_file.uuids.len()
                );
                info!("  Size: {} bytes", dsym_file.data.len());

                uploads.extend(dsym_file.into_uploads());
            }
            Err(e) => {
                tracing::warn!("Failed to process dSYM {}: {}", dsym_path.display(), e);
            }
        }
    }

    if uploads.is_empty() {
        info!("No dSYMs to upload");
        return Ok(());
    }

    info!("Uploading {} dSYM(s)...", uploads.len());
    api::symbol_sets::upload_with_retry(uploads, 10, true)?;
    info!("dSYM upload complete");

    Ok(())
}
