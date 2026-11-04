use std::fmt;

use anyhow::{ensure, Context, Error, Result};
use serde::Deserialize;
use url::Url;

#[derive(Debug, Deserialize)]
#[serde(try_from = "String")]
pub struct WebUrl(Url);

impl WebUrl {
    fn new(url: Url) -> Result<Self> {
        ensure!(
            matches!(url.scheme(), "http" | "https"),
            "The server returned a {} URL. The CLI only opens http and https URLs, so check that your PostHog host is correct",
            url.scheme()
        );
        // On WSL, `open` passes the URL to `wslview`, which puts it in a double-quoted
        // PowerShell string. PowerShell reads none of these characters as syntax there,
        // and PostHog URLs use no others.
        ensure!(
            url.as_str()
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "-._~:/?#[]@&=+,%".contains(c)),
            "The server returned a URL with characters that the CLI does not open, so check that your PostHog host is correct"
        );
        Ok(Self(url))
    }

    pub fn with_query_pair(mut self, name: &str, value: &str) -> Result<Self> {
        self.0.query_pairs_mut().append_pair(name, value);
        Self::new(self.0)
    }

    /// `open::that` runs `cmd /c start` on Windows, and cmd parses the URL as shell syntax.
    /// `open::that_detached` with the `shellexecute-on-windows` feature calls ShellExecuteExW
    /// instead, so cmd does not see the URL.
    #[allow(clippy::disallowed_methods)]
    pub fn open_in_browser(&self) -> Result<()> {
        open::that_detached(self.0.as_str()).context("Failed to open browser")
    }
}

impl TryFrom<String> for WebUrl {
    type Error = Error;

    fn try_from(raw: String) -> Result<Self> {
        Self::new(Url::parse(&raw).context("The server returned a URL that is not valid")?)
    }
}

impl fmt::Display for WebUrl {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
