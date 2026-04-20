use anyhow::{Context, Result};

use crate::invocation_context::context;

use super::{fetch_endpoint, OpenArgs};

pub fn open_endpoint(args: &OpenArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_open");

    let endpoint = fetch_endpoint(&args.name, args.debug)?;

    let ui_url = endpoint
        .ui_url
        .ok_or_else(|| anyhow::anyhow!("Endpoint has no UI URL"))?;

    println!("Opening {ui_url}...");
    open::that(&ui_url).context("Failed to open browser")?;

    Ok(())
}
