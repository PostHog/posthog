use super::homedir::{ensure_homedir_exists, posthog_home_dir};
use anyhow::{Context, Error};
use inquire::{validator::Validation, CustomUserError};
use reqwest::Url;
use tracing::info;

use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Token {
    pub host: Option<String>,
    pub token: String,
    pub env_id: String,
}

impl Token {
    pub fn get_host(&self) -> String {
        self.host
            .clone()
            .unwrap_or("https://us.posthog.com".to_string())
    }
}

pub trait CredentialProvider {
    fn get_credentials(&self) -> Result<Token, Error>;
    fn store_credentials(&self, token: Token) -> Result<(), Error>;
    fn report_location(&self) -> String;
}

pub struct HomeDirProvider;

impl CredentialProvider for HomeDirProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        let home = posthog_home_dir();
        let file = home.join("credentials.json");
        let token = std::fs::read_to_string(file.clone()).context(format!(
            "While trying to read credentials from file {file:?}"
        ))?;
        let token = serde_json::from_str(&token).context("While trying to parse token")?;
        Ok(token)
    }

    fn store_credentials(&self, token: Token) -> Result<(), Error> {
        let home = posthog_home_dir();
        ensure_homedir_exists()?;
        let file = home.join("credentials.json");
        let token = serde_json::to_string(&token).context("While trying to serialize token")?;
        std::fs::write(file.clone(), token).context(format!(
            "While trying to write credentials to file {file:?}",
        ))?;
        Ok(())
    }

    fn report_location(&self) -> String {
        posthog_home_dir()
            .join("credentials.json")
            .to_string_lossy()
            .to_string()
    }
}

/// Tries to read the token from the env var `POSTHOG_CLI_API_KEY`
pub struct EnvVarProvider;

impl CredentialProvider for EnvVarProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        let host = std::env::var("POSTHOG_CLI_HOST").ok();
        // Try POSTHOG_CLI_API_KEY first, fall back to POSTHOG_CLI_TOKEN for backward compatibility
        let token = std::env::var("POSTHOG_CLI_API_KEY")
            .or_else(|_| std::env::var("POSTHOG_CLI_TOKEN"))
            .context("While trying to read env var POSTHOG_CLI_API_KEY")?;
        // Try POSTHOG_CLI_PROJECT_ID first, fall back to POSTHOG_CLI_ENV_ID for backward compatibility
        let env_id = std::env::var("POSTHOG_CLI_PROJECT_ID")
            .or_else(|_| std::env::var("POSTHOG_CLI_ENV_ID"))
            .context("While trying to read env var POSTHOG_CLI_PROJECT_ID")?;
        Ok(Token {
            host,
            token,
            env_id,
        })
    }

    fn store_credentials(&self, _token: Token) -> Result<(), Error> {
        Ok(())
    }

    fn report_location(&self) -> String {
        unimplemented!("We should never try to save a credential to the env");
    }
}

pub fn host_validator(host: &str) -> Result<Validation, CustomUserError> {
    if host.is_empty() || Url::parse(host).is_err() {
        return Ok(Validation::Invalid("Host must be a valid URL".into()));
    }

    Ok(Validation::Valid)
}

/// Returns true if the host is recognizably a PostHog host or a local/self-hosted
/// setup we should not warn about. The goal is to catch host typos like
/// `eu.posthog.co` (missing the `m`) without spamming self-hosters.
pub fn is_known_posthog_host(host: &str) -> bool {
    let Ok(url) = Url::parse(host) else {
        return false;
    };
    let Some(host_str) = url.host_str() else {
        return false;
    };

    if host_str == "localhost" || host_str.parse::<std::net::IpAddr>().is_ok() {
        return true;
    }

    host_str == "posthog.com"
        || host_str == "posthog.dev"
        || host_str.ends_with(".posthog.com")
        || host_str.ends_with(".posthog.dev")
}

/// Heuristic that flags hosts which clearly meant to be a PostHog host but
/// don't quite match (e.g. `eu.posthog.co`). Anything that doesn't mention
/// `posthog` at all is assumed to be a self-hosted deployment and left alone.
pub fn looks_like_posthog_typo(host: &str) -> bool {
    if is_known_posthog_host(host) {
        return false;
    }
    let Ok(url) = Url::parse(host) else {
        return false;
    };
    let Some(host_str) = url.host_str() else {
        return false;
    };
    host_str.contains("posthog")
}

pub fn token_validator(token: &str) -> Result<Validation, CustomUserError> {
    if token.is_empty() {
        return Ok(Validation::Invalid("Token cannot be empty".into()));
    };

    if !token.starts_with("phx_") {
        return Ok(Validation::Invalid(
            "Token looks wrong, must start with 'phx_'".into(),
        ));
    }

    Ok(Validation::Valid)
}

pub fn env_id_validator(env_id: &str) -> Result<Validation, CustomUserError> {
    // Must be a number
    if env_id.is_empty() {
        return Ok(Validation::Invalid("Environment ID cannot be empty".into()));
    }

    // Must be a number
    if env_id.parse::<u32>().is_err() {
        return Ok(Validation::Invalid(
            "Environment ID must be a number".into(),
        ));
    }

    Ok(Validation::Valid)
}

pub fn get_token() -> Result<Token, Error> {
    let env = EnvVarProvider;
    let env_err = match env.get_credentials() {
        Ok(token) => {
            info!("Using token from env var, for environment {}", token.env_id);
            return Ok(token);
        }
        Err(e) => e,
    };
    let provider = HomeDirProvider;
    let dir_err = match provider.get_credentials() {
        Ok(token) => {
            info!(
                "Using token from: {}, for environment {}",
                provider.report_location(),
                token.env_id
            );
            return Ok(token);
        }
        Err(e) => e,
    };

    Err(
        anyhow::anyhow!("Couldn't load credentials... Have you logged in recently?")
            .context(env_err)
            .context(dir_err),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_known_posthog_hosts() {
        assert!(is_known_posthog_host("https://us.posthog.com"));
        assert!(is_known_posthog_host("https://eu.posthog.com"));
        assert!(is_known_posthog_host("https://app.posthog.com"));
        assert!(is_known_posthog_host("https://us.posthog.dev"));
        assert!(is_known_posthog_host("https://posthog.com"));
        assert!(is_known_posthog_host("http://localhost:8000"));
        assert!(is_known_posthog_host("http://127.0.0.1:8010"));
    }

    #[test]
    fn does_not_recognize_typoed_or_self_hosted() {
        assert!(!is_known_posthog_host("https://eu.posthog.co"));
        assert!(!is_known_posthog_host("https://us.posthog.con"));
        assert!(!is_known_posthog_host("https://posthog.example.com"));
        assert!(!is_known_posthog_host("not a url"));
        assert!(!is_known_posthog_host(""));
    }

    #[test]
    fn flags_typos_that_mention_posthog() {
        assert!(looks_like_posthog_typo("https://eu.posthog.co"));
        assert!(looks_like_posthog_typo("https://us.posthog.con"));
        assert!(looks_like_posthog_typo("https://posthog.co"));
    }

    #[test]
    fn does_not_flag_known_or_unrelated_hosts() {
        // Known hosts must never trigger the warning.
        assert!(!looks_like_posthog_typo("https://us.posthog.com"));
        assert!(!looks_like_posthog_typo("https://eu.posthog.com"));
        assert!(!looks_like_posthog_typo("http://localhost:8000"));
        // Self-hosted on an unrelated domain must not be warned about.
        assert!(!looks_like_posthog_typo("https://analytics.example.com"));
        assert!(!looks_like_posthog_typo("https://mycompany.internal"));
        // Anything unparseable is treated as not-a-typo (host_validator already
        // rejects these before we get here).
        assert!(!looks_like_posthog_typo("not a url"));
    }
}
