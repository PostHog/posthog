mod steps;
mod trends;
mod unordered_steps;
mod unordered_trends;

use serde::{Deserialize, Serialize};
use std::env;
use std::io::{self, BufRead, Write};
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

    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let mut stdin = stdin.lock();

    if arg == Some("trends") {
        loop {
            match rmp_serde::from_read(&mut stdin) {
                Ok(value) => {
                    let output = trends::process_line(value);
                    // Serialize to MessagePack
                    let bytes = rmp_serde::to_vec(&output).unwrap();
                    stdout.write_all(&bytes).unwrap();
                    stdout.flush().unwrap();
                }
                Err(e) => {
                    // End of input or error
                    break;
                }
            }
        }
    } else {
        loop {
            match rmp_serde::from_read(&mut stdin) {
                Ok(value) => {
                    let output = steps::process_line(value);
                    // Serialize to MessagePack
                    let bytes = rmp_serde::to_vec(&output).unwrap();
                    stdout.write_all(&bytes).unwrap();
                    stdout.flush().unwrap();
                }
                Err(e) => {
                    // End of input or error
                    break;
                }
            }
        }
    }
}
