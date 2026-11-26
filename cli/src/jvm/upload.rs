use std::{fs, io, path::PathBuf, time::Instant};

use anyhow::{anyhow, bail, Context, Result};
use posthog_symbol_data::{
    symbol_data_known_decompressed_size, write_symbol_data, MAX_JVM_BUNDLE_SOURCES,
};
use serde_json::json;
use tracing::info;

use crate::{
    api::{
        self,
        releases::ReleaseBuilder,
        symbol_sets::{SymbolSetUpload, MAX_FILE_SIZE},
    },
    invocation_context::context,
    jvm::sources::{bundle_sources, collect_sources, MAP_ID_PROPERTY, META_PROPERTIES_FILE},
    sourcemaps::{
        args::{ReleaseArgs, UploadConflictArgs},
        inject::resolve_release_builder,
    },
};

const MAX_DECOMPRESSED_SIZE: usize = 512 * 1024 * 1024;

#[derive(clap::Args, Clone)]
pub struct Args {
    /// A directory of Java or Kotlin source files, such as `src/main/java`. Repeat it for each
    /// source directory of the build. Test sources and build output inside it are skipped.
    #[arg(short, long = "source", required = true)]
    pub sources: Vec<PathBuf>,

    /// After the upload, write `posthog-meta.properties` with the id of the uploaded sources into
    /// this directory. Package it on the application's classpath, so the PostHog SDK sends the id
    /// with each exception and PostHog can find the sources.
    #[arg(long, value_name = "DIR")]
    pub meta_out: Option<PathBuf>,

    /// When no PostHog credentials are configured, skip the upload with a warning instead of
    /// failing. Build plugins pass it, so that builds on machines without PostHog credentials
    /// keep working. A skipped upload writes no `posthog-meta.properties`.
    #[arg(long)]
    pub skip_without_credentials: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,
}

/// Removes the `posthog-meta.properties` that an earlier upload wrote into `--meta-out`. It runs
/// before any step that can skip or fail the upload, so that a build which reuses its output
/// directory never packages the id of an earlier upload.
pub fn remove_previous_meta(args: &Args) -> Result<()> {
    let Some(dir) = &args.meta_out else {
        return Ok(());
    };
    let path = dir.join(META_PROPERTIES_FILE);
    match fs::remove_file(&path) {
        Err(e) if e.kind() != io::ErrorKind::NotFound => {
            Err(e).with_context(|| format!("Failed to remove {}", path.display()))
        }
        _ => Ok(()),
    }
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("jvm_upload");
    let Args {
        sources: roots,
        meta_out,
        // Handled before the credentials are loaded, in `commands.rs`.
        skip_without_credentials: _,
        batch_size,
        release,
        conflict,
    } = args;

    let sources = collect_sources(roots)?;
    if sources.is_empty() {
        let roots: Vec<String> = roots.iter().map(|r| r.display().to_string()).collect();
        bail!(
            "No Java or Kotlin source files found in {}",
            roots.join(", ")
        );
    }
    let file_count = sources.len();
    if file_count > MAX_JVM_BUNDLE_SOURCES {
        bail!(
            "Found {file_count} source files, more than the {MAX_JVM_BUNDLE_SOURCES} PostHog \
             accepts in one upload. Upload fewer source directories."
        );
    }

    let resolved_release = release.resolve_info_plist()?;
    let skip_release_on_fail = resolved_release.skip_release_on_fail;

    let directory = roots[0]
        .canonicalize()
        .map_err(|e| anyhow!("Path {} canonicalization failed: {}", roots[0].display(), e))?;
    // Bind the sources to the release this build resolved, so that frames resolved with them
    // carry its git metadata and their events resolve to this release.
    let release = resolve_release_builder(&directory, resolved_release)?
        .map(ReleaseBuilder::fetch_or_create)
        .transpose()?;

    let bundle = bundle_sources(sources, release.as_ref().map(|r| r.hash_id.as_str()))?;
    info!("Bundled {file_count} source files as {}", bundle.id);

    let data = write_symbol_data(bundle.bundle)?;
    check_bundle_size(&data, file_count, MAX_FILE_SIZE, MAX_DECOMPRESSED_SIZE)?;

    let total_bytes = data.len();
    let to_upload = SymbolSetUpload {
        chunk_id: bundle.id.clone(),
        release_id: release.map(|r| r.id.to_string()),
        data,
        content_hash: Some(bundle.content_hash),
    };
    let started_at = Instant::now();
    let (summary, upload_result) = api::symbol_sets::upload_with_retry(
        vec![to_upload],
        *batch_size,
        skip_release_on_fail,
        conflict.force,
        conflict.skip_on_conflict,
    );
    let mut props = vec![
        ("file_count", json!(file_count)),
        ("total_bytes", json!(total_bytes)),
        ("duration_ms", json!(started_at.elapsed().as_millis())),
        ("success", json!(upload_result.is_ok())),
    ];
    props.extend(summary.telemetry_props());
    if let Err(ref e) = upload_result {
        props.push(("error", json!(format!("{e:#}"))));
    }
    context().capture_event("error_tracking_cli_jvm_upload_finished", props);
    upload_result?;

    // Written only after a successful upload: an app that sends an id PostHog has no sources for
    // gets its frames marked as failed to resolve instead of shown as they are.
    if let Some(dir) = meta_out {
        fs::create_dir_all(dir).with_context(|| format!("Failed to create {}", dir.display()))?;
        let path = dir.join(META_PROPERTIES_FILE);
        fs::write(&path, format!("{MAP_ID_PROPERTY}={}\n", bundle.id))
            .with_context(|| format!("Failed to write {}", path.display()))?;
        info!("Wrote {}", path.display());
    }

    crate::safe_println!("{}", bundle.id);
    Ok(())
}

// The upload skips a symbol set above its size limit with only a warning, and PostHog fails to
// read one that decompresses past its limit. The id of such a bundle must not reach the app,
// because every frame that carries it then fails to resolve.
fn check_bundle_size(
    data: &[u8],
    file_count: usize,
    max_size: usize,
    max_decompressed_size: usize,
) -> Result<()> {
    let megabytes = |bytes: usize| bytes.div_ceil(1024 * 1024);
    if data.len() > max_size {
        bail!(
            "The {file_count} source files bundle to {} MB, more than the {} MB PostHog accepts. \
             Upload fewer source directories, for example without generated sources.",
            megabytes(data.len()),
            max_size / (1024 * 1024),
        );
    }
    let decompressed_size = symbol_data_known_decompressed_size(data)?.unwrap_or_default();
    if decompressed_size > max_decompressed_size {
        bail!(
            "The {file_count} source files hold {} MB of text, more than the {} MB PostHog reads \
             from one upload. Upload fewer source directories, for example without generated \
             sources.",
            megabytes(decompressed_size),
            max_decompressed_size / (1024 * 1024),
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use posthog_symbol_data::JvmBundle;

    use super::*;

    #[test]
    fn a_bundle_that_decompresses_past_the_limit_is_rejected() {
        let data = write_symbol_data(JvmBundle {
            mapping: None,
            sources: [("com/acme/Big.java".to_string(), "a".repeat(2 * 1024 * 1024))].into(),
        })
        .unwrap();
        assert!(data.len() < 1024 * 1024);

        assert!(check_bundle_size(&data, 1, MAX_FILE_SIZE, 4 * 1024 * 1024).is_ok());
        let error = check_bundle_size(&data, 1, MAX_FILE_SIZE, 1024 * 1024).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("more than the 1 MB PostHog reads"),
            "{error}"
        );
    }
}
