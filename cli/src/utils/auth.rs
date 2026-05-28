use super::homedir::{ensure_homedir_exists, posthog_home_dir};
use anyhow::{Context, Error};
use inquire::{validator::Validation, CustomUserError};
use reqwest::Url;
use std::collections::HashMap;
use std::path::Path;
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

/// Reads credentials atomically from a single source. The first source that supplies both
/// `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID` (or their legacy aliases) wins; `host`
/// is optional and is only read from that same source. Order: process env → `.env.local` → `.env`.
pub struct EnvVarProvider;

fn load_dotenv(path: &Path) -> HashMap<String, String> {
    let Ok(iter) = dotenvy::from_path_iter(path) else {
        return HashMap::new();
    };
    iter.flatten().collect()
}

fn try_source<F: Fn(&str) -> Option<String>>(lookup: F) -> Option<Token> {
    let token = lookup("POSTHOG_CLI_API_KEY").or_else(|| lookup("POSTHOG_CLI_TOKEN"))?;
    let env_id = lookup("POSTHOG_CLI_PROJECT_ID").or_else(|| lookup("POSTHOG_CLI_ENV_ID"))?;
    let host = lookup("POSTHOG_CLI_HOST");
    Some(Token {
        host,
        token,
        env_id,
    })
}

impl CredentialProvider for EnvVarProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        if let Some(t) = try_source(|n| std::env::var(n).ok()) {
            return Ok(t);
        }
        let local = load_dotenv(Path::new(".env.local"));
        if let Some(t) = try_source(|n| local.get(n).cloned()) {
            return Ok(t);
        }
        let dotenv = load_dotenv(Path::new(".env"));
        if let Some(t) = try_source(|n| dotenv.get(n).cloned()) {
            return Ok(t);
        }
        anyhow::bail!(
            "Couldn't find POSTHOG_CLI_API_KEY (or POSTHOG_CLI_TOKEN) and \
             POSTHOG_CLI_PROJECT_ID (or POSTHOG_CLI_ENV_ID) in process env, .env.local, or .env"
        )
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
            info!(
                "Using token from environment or dotenv file, for environment {}",
                token.env_id
            );
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

    fn lookup<'a>(map: &'a HashMap<&'a str, &'a str>) -> impl Fn(&str) -> Option<String> + 'a {
        move |k| map.get(k).map(|v| v.to_string())
    }

    #[test]
    fn try_source_returns_none_when_required_missing() {
        let map = HashMap::new();
        assert!(try_source(lookup(&map)).is_none());
    }

    #[test]
    fn try_source_requires_both_api_key_and_project_id() {
        let mut only_key = HashMap::new();
        only_key.insert("POSTHOG_CLI_API_KEY", "phx_abc");
        assert!(try_source(lookup(&only_key)).is_none());

        let mut only_id = HashMap::new();
        only_id.insert("POSTHOG_CLI_PROJECT_ID", "1");
        assert!(try_source(lookup(&only_id)).is_none());
    }

    #[test]
    fn try_source_accepts_legacy_aliases() {
        let mut map = HashMap::new();
        map.insert("POSTHOG_CLI_TOKEN", "phx_legacy");
        map.insert("POSTHOG_CLI_ENV_ID", "42");
        let token = try_source(lookup(&map)).expect("should resolve");
        assert_eq!(token.token, "phx_legacy");
        assert_eq!(token.env_id, "42");
        assert!(token.host.is_none());
    }

    #[test]
    fn try_source_prefers_canonical_over_legacy() {
        let mut map = HashMap::new();
        map.insert("POSTHOG_CLI_API_KEY", "phx_new");
        map.insert("POSTHOG_CLI_TOKEN", "phx_old");
        map.insert("POSTHOG_CLI_PROJECT_ID", "1");
        map.insert("POSTHOG_CLI_ENV_ID", "2");
        let token = try_source(lookup(&map)).unwrap();
        assert_eq!(token.token, "phx_new");
        assert_eq!(token.env_id, "1");
    }

    #[test]
    fn try_source_host_is_optional() {
        let mut map = HashMap::new();
        map.insert("POSTHOG_CLI_API_KEY", "phx_abc");
        map.insert("POSTHOG_CLI_PROJECT_ID", "1");
        let token = try_source(lookup(&map)).unwrap();
        assert!(token.host.is_none());
    }

    #[test]
    fn try_source_picks_up_host_from_same_source() {
        let mut map = HashMap::new();
        map.insert("POSTHOG_CLI_API_KEY", "phx_abc");
        map.insert("POSTHOG_CLI_PROJECT_ID", "1");
        map.insert("POSTHOG_CLI_HOST", "https://eu.posthog.com");
        let token = try_source(lookup(&map)).unwrap();
        assert_eq!(token.host.as_deref(), Some("https://eu.posthog.com"));
    }

    #[test]
    fn try_source_ignores_host_when_required_missing() {
        // Host alone is not enough to count as a valid source — it must not leak through.
        let mut map = HashMap::new();
        map.insert("POSTHOG_CLI_HOST", "https://attacker.example");
        assert!(try_source(lookup(&map)).is_none());
    }
}
