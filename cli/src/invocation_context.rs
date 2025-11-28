use anyhow::Result;
use inquire::{
    validator::{ErrorMessage, Validation},
    CustomUserError,
};
use posthog_rs::Event;
use reqwest::blocking::Client;
use std::{
    io::{self, IsTerminal},
    sync::{Mutex, OnceLock},
    thread::JoinHandle,
};
use tracing::{debug, info, warn};

use crate::{
    api::client::PHClient,
    utils::auth::{env_id_validator, get_token, host_validator, token_validator},
};

// I've decided in my infinite wisdom that global state is fine, actually.
pub static INVOCATION_CONTEXT: OnceLock<InvocationContext> = OnceLock::new();

pub struct InvocationContext {
    pub config: InvocationConfig,
    pub client: PHClient,
    pub is_terminal: bool,

    handles: Mutex<Vec<JoinHandle<()>>>,
}

pub fn context() -> &'static InvocationContext {
    INVOCATION_CONTEXT.get().expect("Context has been set up")
}

pub fn init_context(host: Option<String>, skip_ssl: bool) -> Result<()> {
    let token = get_token()?;
    let config = InvocationConfig {
        api_key: token.token.clone(),
        host: host.unwrap_or(token.host.unwrap_or("https://us.i.posthog.com".into())),
        env_id: token.env_id.clone(),
        skip_ssl,
    };

    config.validate()?;

    let client: PHClient = PHClient::from_config(config.clone())?;

    INVOCATION_CONTEXT.get_or_init(|| InvocationContext::new(config, client));

    // This is pulled at compile time, not runtime - we set it at build.
    if let Some(token) = option_env!("POSTHOG_API_TOKEN") {
        let ph_config = posthog_rs::ClientOptionsBuilder::default()
            .api_key(token.to_string())
            .request_timeout_seconds(5) // It's a CLI, 5 seconds is an eternity
            .build()
            .expect("Building PH config succeeds");
        posthog_rs::init_global(ph_config).expect("Initializing PostHog client");
    } else {
        warn!("Posthog api token not set at build time - is this a debug build?");
    };

    Ok(())
}

#[derive(Clone)]
pub struct InvocationConfig {
    pub api_key: String,
    pub host: String,
    pub env_id: String,
    pub skip_ssl: bool,
}

impl InvocationConfig {
    pub fn validate(&self) -> Result<()> {
        fn handle_validation(
            validation: Result<Validation, CustomUserError>,
            context: &str,
        ) -> Result<()> {
            let validation = validation.map_err(|err| anyhow::anyhow!("{context}: {err}"))?;
            if let Validation::Invalid(ErrorMessage::Custom(msg)) = validation {
                anyhow::bail!("{context}: {msg:?}");
            }
            Ok(())
        }

        handle_validation(token_validator(&self.api_key), "Invalid Personal API key")?;
        handle_validation(host_validator(&self.host), "Invalid Host")?;
        handle_validation(env_id_validator(&self.env_id), "Invalid Environment ID")?;
        Ok(())
    }
}

impl InvocationContext {
    pub fn new(config: InvocationConfig, client: PHClient) -> Self {
        Self {
            config,
            client,
            is_terminal: io::stdout().is_terminal(),
            handles: Default::default(),
        }
    }

    pub fn build_http_client(&self) -> Result<Client> {
        let client = Client::builder()
            .danger_accept_invalid_certs(self.config.skip_ssl)
            .build()?;
        Ok(client)
    }

    pub fn capture_command_invoked(&self, command: &str) {
        let env_id = self.client.get_env_id();
        let event_name = "posthog cli command run".to_string();
        let mut event = Event::new_anon(event_name);

        event
            .insert_prop("command_name", command)
            .expect("Inserting command prop succeeds");

        event
            .insert_prop("env_id", env_id)
            .expect("Inserting env_id prop succeeds");

        let handle = std::thread::spawn(move || {
            debug!("Capturing event");
            let res = posthog_rs::capture(event); // Purposefully ignore errors here
            if let Err(err) = res {
                debug!("Failed to capture event: {:?}", err);
            } else {
                debug!("Event captured successfully");
            }
        });

        self.handles.lock().unwrap().push(handle);
    }

    pub fn finish(&self) {
        info!("Finishing up....");

        self.handles
            .lock()
            .unwrap()
            .drain(..)
            .for_each(|handle| handle.join().unwrap());

        info!("Finished!")
    }
}
