mod parsing;
mod steps;
mod trends;
mod unordered_steps;
mod unordered_trends;

use serde::{Deserialize, Serialize};
use std::env;
use std::io::{self, BufRead, Write};

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
enum PropVal {
    String(String),
    Vec(Vec<String>),
    Int(u64),
    VecInt(Vec<u64>),
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(r#""hello""#, PropVal::String("hello".to_string()))]
    #[case(r#"42"#, PropVal::Int(42))]
    #[case(r#"4503599627370496"#, PropVal::Int(4503599627370496))] // 2^52 (NOT_IN_COHORT_ID)
    #[case(r#"["a","b"]"#, PropVal::Vec(vec!["a".to_string(), "b".to_string()]))]
    #[case(r#"[1, 2, 3]"#, PropVal::VecInt(vec![1, 2, 3]))]
    #[case(r#"[4503599627370496]"#, PropVal::VecInt(vec![4503599627370496]))]
    fn test_propval_deserialization(#[case] json: &str, #[case] expected: PropVal) {
        let result: PropVal = serde_json::from_str(json).unwrap();
        assert_eq!(result, expected);
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let arg = args.get(1).map(|x| x.as_str());

    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        if let Ok(line) = line {
            let output = match arg {
                Some("trends") => trends::process_line(&line),
                _ => steps::process_line(&line),
            };
            writeln!(stdout, "{}", output).unwrap();
            stdout.flush().unwrap();
        }
    }
}
