use anyhow::Result;
use posthog_rs::Event;
use reqwest::blocking::Client;
use std::{
    sync::{Mutex, OnceLock},
    thread::JoinHandle,
};
use tracing::{debug, info, warn};

use crate::utils::auth::{get_token, Token};

// I've decided in my infinite wisdom that global state is fine, actually.
pub static INVOCATION_CONTEXT: OnceLock<InvocationContext> = OnceLock::new();

pub struct InvocationContext {
    pub token: Token,
    pub client: Client,

    handles: Mutex<Vec<JoinHandle<()>>>,
}

pub fn context() -> &'static InvocationContext {
    INVOCATION_CONTEXT.get().expect("Context has been set up")
}

pub fn init_context(host: Option<String>, skip_ssl: bool) -> Result<()> {
    let mut token = get_token()?;
    if let Some(host) = host {
        // If the user passed a host, respect it
        token.host = Some(host);
    }

    let client = reqwest::blocking::Client::builder()
        .danger_accept_invalid_certs(skip_ssl)
        .build()?;

    INVOCATION_CONTEXT.get_or_init(|| InvocationContext::new(token, client));

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

impl InvocationContext {
    pub fn new(token: Token, client: Client) -> Self {
        Self {
            token,
            client,
            handles: Default::default(),
        }
    }

    pub fn capture_command_invoked(&self, command: &str) {
        let env_id = &self.token.env_id;
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
