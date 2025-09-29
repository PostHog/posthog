use std::sync::Mutex;

use anyhow::Result;
use reqwest::blocking::Client;

// Olly can have a little global state, as a treat. I could make this a OnceCell, to assert it's written to exactly once, and that'd
// probably make it more correct, or at least more difficult to misuse. Alas, war mode.
pub static SKIP_SSL: Mutex<bool> = Mutex::new(false);

pub fn get_client() -> Result<Client> {
    Ok(reqwest::blocking::Client::builder()
        .danger_accept_invalid_certs(*SKIP_SSL.lock().unwrap())
        .build()?)
}
