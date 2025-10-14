use anyhow::Error;
use inquire::Text;
use tracing::info;

use crate::utils::{
    auth::{host_validator, token_validator, CredentialProvider, HomeDirProvider, Token},
    posthog::capture_command_invoked,
};

pub fn login() -> Result<(), Error> {
    let host = Text::new("Enter the PostHog host URL")
        .with_default("https://us.posthog.com")
        .with_validator(host_validator)
        .prompt()?;

    let env_id =
        Text::new("Enter your project ID (the number in your posthog homepage url)").prompt()?;

    // Given this is an interactive command, we're happy enough to not join the capture handle
    let _ = capture_command_invoked("interactive_login", Some(env_id.clone()));

    let token = Text::new(
        "Enter your personal API token (see posthog.com/docs/api#private-endpoint-authentication)",
    )
    .with_validator(token_validator)
    .prompt()?;

    let token = Token {
        host: Some(host),
        token,
        env_id,
    };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;
    info!("Token saved to: {}", provider.report_location());
    Ok(())
}
