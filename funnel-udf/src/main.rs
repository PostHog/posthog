mod steps;
mod trends;
mod unordered_steps;
mod unordered_trends;

use serde::{Deserialize, Serialize};
use std::env;
use std::io::{self, BufRead, Write};
use serde_json::Value;
use rmp_serde;

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
enum PropVal {
    String(String),
    Vec(Vec<String>),
    Int(u32),
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let arg = args.get(1).map(|x| x.as_str());
    let use_json = args.get(2).map_or(false, |x| x == "--json");

    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        if let Ok(line) = line {
            let output = match arg {
                Some("trends") => trends::process_line(&line),
                _ => steps::process_line(&line),
            };
            
            if !use_json {
                // Serialize to MessagePack
                let bytes = rmp_serde::to_vec(&output).unwrap();
                stdout.write_all(&bytes).unwrap();
            } else {
                // Use JSON as before
                writeln!(stdout, "{}", output).unwrap();
            }
            stdout.flush().unwrap();
        }
    }
}
