// Inject-minified is identical to injecting web-facing bundles, just with slightly different search parameters
// It's intended as an escape hatch for people rolling their own build pipeline - we expect most users to be
// using the metro plugin for injecting, and then calling clone

use anyhow::{bail, Result};
use walkdir::DirEntry;

use crate::{
    invocation_context::context,
    sourcemaps::inject::{inject_impl, InjectArgs},
};

pub fn inject(args: &InjectArgs) -> Result<()> {
    context().capture_command_invoked("hermes_inject");
    args.validate()?;
    // The rest of the Hermes pipeline (clone, upload, the RN SDK) has no release-unbinding
    // support, so accepting the flag would inject a global nothing reads while upload
    // re-binds the release anyway. Rejecting also catches a POSTHOG_NO_RELEASE_BIND env var
    // set for a web build leaking into a React Native build in the same environment.
    if args.no_release_bind {
        bail!("--no-release-bind is not supported for Hermes bundles. Remove the flag (or unset POSTHOG_NO_RELEASE_BIND) and inject again.");
    }
    inject_impl(args, is_metro_bundle, None)
}

pub fn is_metro_bundle(entry: &DirEntry) -> bool {
    entry.file_type().is_file()
        && entry
            .path()
            .extension()
            .is_some_and(|ext| ext == "bundle" || ext == "jsbundle")
}
