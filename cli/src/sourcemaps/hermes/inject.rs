// Inject-minified is identical to injecting web-facing bundles, just with slightly different search parameters
// It's intended as an escape hatch for people rolling their own build pipeline - we expect most users to be
// using the metro plugin for injecting, and then calling clone

use anyhow::Result;
use walkdir::DirEntry;

use crate::{
    invocation_context::context,
    sourcemaps::inject::{inject_impl, InjectArgs},
};

pub fn inject(args: &InjectArgs) -> Result<()> {
    context().capture_command_invoked("hermes_inject");
    inject_impl(args, is_metro_bundle)
}

pub fn is_metro_bundle(entry: &DirEntry) -> bool {
    entry.file_type().is_file()
        && entry
            .path()
            .extension()
            .is_some_and(|ext| ext == "bundle" || ext == "jsbundle")
}
