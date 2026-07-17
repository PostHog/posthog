use anyhow::Result;
use inquire::{
    validator::{ErrorMessage, Validation},
    CustomUserError,
};
use posthog_rs::{ErrorTrackingOptionsBuilder, Event};
use reqwest::blocking::Client;
use std::{
    io::{self, IsTerminal},
    path::PathBuf,
    sync::{Mutex, OnceLock},
    thread::JoinHandle,
};
use tracing::debug;
use uuid::Uuid;

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

struct TelemetryContext {
    invocation_id: String,
    command_name: Option<String>,
    env_id: Option<String>,
    is_terminal: bool,
}

static TELEMETRY_CONTEXT: OnceLock<Mutex<TelemetryContext>> = OnceLock::new();

fn telemetry_context() -> &'static Mutex<TelemetryContext> {
    TELEMETRY_CONTEXT.get_or_init(|| {
        Mutex::new(TelemetryContext {
            invocation_id: Uuid::now_v7().to_string(),
            command_name: None,
            env_id: None,
            is_terminal: io::stdout().is_terminal(),
        })
    })
}

pub fn set_telemetry_command_name(command_name: &str) {
    if let Ok(mut context) = telemetry_context().lock() {
        context.command_name = Some(command_name.to_string());
    }
}

fn set_telemetry_env_id(env_id: &str) {
    if let Ok(mut context) = telemetry_context().lock() {
        context.env_id = Some(env_id.to_string());
    }
}

fn apply_telemetry_properties(event: &mut Event) {
    let _ = event.insert_prop("cli_version", env!("CARGO_PKG_VERSION"));
    let _ = event.insert_prop("invocation_id", telemetry_invocation_id());
    let _ = event.insert_prop("is_ci", std::env::var_os("CI").is_some());
    let _ = event.insert_prop("is_terminal", telemetry_is_terminal());
    let _ = event.insert_prop("os", std::env::consts::OS);
    let _ = event.insert_prop("arch", std::env::consts::ARCH);

    if let Some(command_name) = telemetry_command_name() {
        let _ = event.insert_prop("command_name", command_name);
    }

    if let Some(env_id) = telemetry_env_id() {
        let _ = event.insert_prop("env_id", env_id);
    }
}

fn telemetry_invocation_id() -> String {
    telemetry_context()
        .lock()
        .map(|context| context.invocation_id.clone())
        .unwrap_or_else(|_| "unknown".to_string())
}

fn telemetry_command_name() -> Option<String> {
    telemetry_context()
        .lock()
        .ok()
        .and_then(|context| context.command_name.clone())
}

pub fn current_telemetry_command_name() -> Option<String> {
    telemetry_command_name()
}

fn telemetry_env_id() -> Option<String> {
    telemetry_context()
        .lock()
        .ok()
        .and_then(|context| context.env_id.clone())
}

fn telemetry_is_terminal() -> bool {
    telemetry_context()
        .lock()
        .map(|context| context.is_terminal)
        .unwrap_or_else(|_| io::stdout().is_terminal())
}

pub fn context() -> &'static InvocationContext {
    INVOCATION_CONTEXT.get().expect("Context has been set up")
}

pub fn init_posthog_telemetry() {
    let Some(token) = option_env!("POSTHOG_API_TOKEN") else {
        debug!("Posthog api token not set at build time - is this a debug build?");
        return;
    };

    let error_tracking = ErrorTrackingOptionsBuilder::default()
        .capture_panics(true)
        .build()
        .expect("Building error tracking config succeeds");
    let ph_config = posthog_rs::ClientOptionsBuilder::default()
        .api_key(token.to_string())
        .request_timeout_seconds(5) // It's a CLI, 5 seconds is an eternity
        .error_tracking(error_tracking)
        .before_send(|mut event| {
            apply_telemetry_properties(&mut event);
            Some(event)
        })
        .build()
        .expect("Building PH config succeeds");

    match posthog_rs::init_global(ph_config) {
        Ok(()) => {}
        Err(posthog_rs::Error::AlreadyInitialized) => {
            debug!("PostHog client already initialized");
        }
        Err(err) => {
            debug!("PostHog client unavailable: {err:?}");
        }
    }
}

pub fn init_context(
    host: Option<String>,
    skip_ssl: bool,
    rate_limit: Option<usize>,
    env_file: Option<PathBuf>,
) -> Result<()> {
    let token = get_token(env_file)?;
    let config = InvocationConfig {
        api_key: token.token.clone(),
        host: host.unwrap_or(token.host.unwrap_or("https://us.i.posthog.com".into())),
        env_id: token.env_id.clone(),
        skip_ssl,
        rate_limit: rate_limit.unwrap_or(480),
    };

    config.validate()?;
    set_telemetry_env_id(&config.env_id);

    let client: PHClient = PHClient::from_config(config.clone())?;

    INVOCATION_CONTEXT.get_or_init(|| InvocationContext::new(config, client));

    Ok(())
}

#[derive(Clone)]
pub struct InvocationConfig {
    pub api_key: String,
    pub host: String,
    pub env_id: String,
    pub skip_ssl: bool,
    pub rate_limit: usize, // max number of requests per minute
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
        set_telemetry_command_name(command);
        self.capture_event("posthog cli command run", Vec::new());
    }

    pub fn capture_event(&self, event_name: &str, props: Vec<(&str, serde_json::Value)>) {
        let event_name = event_name.to_string();
        let props: Vec<(String, serde_json::Value)> =
            props.into_iter().map(|(k, v)| (k.to_string(), v)).collect();

        let handle = std::thread::spawn(move || {
            let mut event = Event::new_anon(event_name);

            for (key, value) in &props {
                event
                    .insert_prop(key, value)
                    .expect("Inserting prop succeeds");
            }

            debug!("Capturing event");
            posthog_rs::capture(event);
            debug!("Event queued successfully");
        });

        self.handles.lock().unwrap().push(handle);
    }

    pub fn finish(&self) {
        self.handles
            .lock()
            .unwrap()
            .drain(..)
            .for_each(|handle| handle.join().unwrap());
        posthog_rs::flush();
    }
}
