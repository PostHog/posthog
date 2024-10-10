mod steps;
mod trends;

use crate::steps::process_line;
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Write};

#[derive(Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
enum PropVal {
    String(String),
    Vec(Vec<String>),
    Int(u32),
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        if let Ok(line) = line {
            writeln!(stdout, "{}", process_line(&line)).unwrap();
            stdout.flush().unwrap();
        }
    }
}