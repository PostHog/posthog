use std::fmt;

use anyhow::{ensure, Context, Error, Result};
use serde::Deserialize;
use url::Url;

#[derive(Debug, Deserialize)]
#[serde(try_from = "String")]
pub struct WebUrl(Url);

impl WebUrl {
    pub fn append_query_pair(&mut self, name: &str, value: &str) {
        self.0.query_pairs_mut().append_pair(name, value);
    }

    /// `open::that` runs `cmd /c start` on Windows, and cmd parses the URL as shell syntax.
    /// `open::that_detached` with the `shellexecute-on-windows` feature calls ShellExecuteExW
    /// instead, so no shell sees the URL.
    pub fn open_in_browser(&self) -> Result<()> {
        open::that_detached(self.0.as_str()).context("Failed to open browser")
    }
}

impl TryFrom<String> for WebUrl {
    type Error = Error;

    fn try_from(raw: String) -> Result<Self> {
        let url = Url::parse(&raw).context("The server returned a URL that is not valid")?;
        ensure!(
            matches!(url.scheme(), "http" | "https"),
            "The server returned a {} URL. The CLI only opens http and https URLs, so check that your PostHog host is correct",
            url.scheme()
        );
        Ok(Self(url))
    }
}

impl fmt::Display for WebUrl {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
