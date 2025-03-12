mod steps;
mod trends;
mod unordered_steps;
mod unordered_trends;

use serde::{Deserialize, Serialize};
use std::env;
use std::io::{self, BufRead, Write};
use rmp_serde;
use serde_json::json;


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
            // Handle different return types from trends and steps
            if arg == Some("trends") {
                let output = trends::process_line(&line);
                if !use_json {
                    // Serialize to MessagePack
                    let bytes = rmp_serde::to_vec(&output).unwrap();
                    stdout.write_all(&bytes).unwrap();
                } else {
                    // Use JSON
                    writeln!(stdout, "{}", json!({"result": output})).unwrap();
                }
            } else {
                let output = steps::process_line(&line);
                if !use_json {
                    // Serialize to MessagePack
                    let bytes = rmp_serde::to_vec(&output).unwrap();
                    stdout.write_all(&bytes).unwrap();
                } else {
                    // Use JSON
                    writeln!(stdout, "{}", json!({"result": output})).unwrap();
                }
            }
            stdout.flush().unwrap();
        }
    }
}
