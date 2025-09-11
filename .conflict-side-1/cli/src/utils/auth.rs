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
    pub fn get_host(&self, host: Option<&str>) -> String {
        host.map(str::to_string)
            .unwrap_or_else(|| {
                self.host
                    .clone()
                    .unwrap_or("https://us.posthog.com".to_string())
            })
            .to_string()
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

/// Tries to read the token from the env var `POSTHOG_CLI_TOKEN`
pub struct EnvVarProvider;

impl CredentialProvider for EnvVarProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        let host = std::env::var("POSTHOG_CLI_HOST").ok();
        let token = std::env::var("POSTHOG_CLI_TOKEN").context("While trying to read env var")?;
        let env_id = std::env::var("POSTHOG_CLI_ENV_ID").context("While trying to read env var")?;
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

pub fn load_token() -> Result<Token, Error> {
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
