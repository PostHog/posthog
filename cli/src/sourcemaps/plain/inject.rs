use anyhow::Result;

use walkdir::DirEntry;

use crate::{
    invocation_context::context,
    sourcemaps::inject::{inject_impl, InjectArgs},
};

pub fn inject(args: &InjectArgs) -> Result<()> {
    context().capture_command_invoked("sourcemap_inject");
    inject_impl(args, is_javascript_file)
}

pub fn is_javascript_file(entry: &DirEntry) -> bool {
    entry.file_type().is_file()
        && entry
            .path()
            .extension()
            .is_some_and(|ext| ext == "js" || ext == "mjs" || ext == "cjs")
}
