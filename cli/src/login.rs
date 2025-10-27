use anyhow::Error;
use inquire::Text;
use tracing::info;

use crate::{
    invocation_context::{context, init_context},
    utils::auth::{host_validator, token_validator, CredentialProvider, HomeDirProvider, Token},
};

pub fn login() -> Result<(), Error> {
    let host = Text::new("Enter the PostHog host URL")
        .with_default("https://us.posthog.com")
        .with_validator(host_validator)
        .prompt()?;

    let env_id =
        Text::new("Enter your project ID (the number in your posthog homepage url)").prompt()?;

    let token = Text::new(
        "Enter your personal API token",
    )
    .with_validator(token_validator)
    .with_help_message("See posthog.com/docs/api#private-endpoint-authentication. It will need to have the 'error tracking write' scope.")
    .prompt()?;

    let token = Token {
        host: Some(host),
        token,
        env_id,
    };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;
    info!("Token saved to: {}", provider.report_location());

    // Login is the only command that doesn't have a context coming in - because it modifies the context
    init_context(None, false)?;
    context().capture_command_invoked("interactive_login");

    Ok(())
}
