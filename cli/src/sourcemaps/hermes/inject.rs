// Inject-minified is identical to injecting web-facing bundles, just with slightly different search parameters
// It's intended as an escape hatch for people rolling their own build pipeline - we expect most users to be
// using the metro plugin for injecting, and then calling clone

use anyhow::Result;
use walkdir::DirEntry;

use crate::{
    invocation_context::context,
    sourcemaps::inject::{inject_impl, EventReleaseSource, InjectArgs},
};

pub fn inject(args: &InjectArgs) -> Result<()> {
    context().capture_command_invoked("hermes_inject");
    args.validate()?;
    // A React Native app reports its release from the app metadata it already sends. Event mode
    // therefore injects chunk ids and nothing else here. A release id in the chunk would do
    // nothing, because the bundle compiles to Hermes bytecode and no SDK reads the global.
    inject_impl(args, is_metro_bundle, None, EventReleaseSource::AppMetadata)
}

pub fn is_metro_bundle(entry: &DirEntry) -> bool {
    entry.file_type().is_file()
        && entry
            .path()
            .extension()
            .is_some_and(|ext| ext == "bundle" || ext == "jsbundle")
}
