use reqwest::blocking::Client;
use serde::de::DeserializeOwned;

pub trait Paginated<T>: DeserializeOwned {
    fn next(&self) -> Option<&str>;
    fn into_items(self) -> Vec<T>;
}

pub fn fetch_paginated<T, R>(client: &Client, start_url: &str, token: &str) -> Result<Vec<T>, anyhow::Error>
where
    T: DeserializeOwned,
    R: Paginated<T>,
{
    let mut items = Vec::new();
    let mut next = Some(start_url.to_string());

    while let Some(url) = next {
        let resp = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/json")
            .send()?;

        if !resp.status().is_success() {
            let e = resp.text()?;
            return Err(anyhow::anyhow!("Request failed: {}", e));
        }

        let page: R = resp.json()?;
        let next_link = page.next().map(|s| s.to_string());
        items.extend(page.into_items());
        next = next_link;
    }

    Ok(items)
}