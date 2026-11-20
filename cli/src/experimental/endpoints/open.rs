use anyhow::Result;

use crate::{invocation_context::context, utils::web_url::WebUrl};

use super::{fetch_endpoint, OpenArgs};

pub fn open_endpoint(args: &OpenArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_open");

    let endpoint = fetch_endpoint(&args.name, args.debug)?;

    let ui_url = endpoint
        .ui_url
        .ok_or_else(|| anyhow::anyhow!("Endpoint has no UI URL"))?;
    let ui_url = WebUrl::try_from(ui_url)?;

    crate::safe_println!("Opening {ui_url}...");
    ui_url.open_in_browser()?;

    Ok(())
}
