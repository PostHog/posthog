// Each golden comes from posthog-cli's own container code (cli/examples/hog_parity_oracle.rs). A
// mismatch means hog would upload different bytes than posthog-cli, and PostHog would reject a
// re-upload of the same file with `content_hash_mismatch`.

use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo, HermesMap, ProguardMapping};
use serde::Deserialize;

use crate::upload::content_hash;

const GOLDEN: &str = include_str!("../../test/parity/golden/containers.json");
const LINE_WORDS: [&str; 7] = [
    "com.example.app.Model",
    "getValue",
    "setValue",
    "onCreate",
    "java.lang.String",
    "int",
    "void",
];
const PRINTABLE_START: u32 = 32;
const PRINTABLE_COUNT: u32 = 95;

#[derive(Deserialize)]
struct Case {
    r#type: String,
    input: Input,
    hash: String,
}

#[derive(Deserialize)]
struct Input {
    generator: String,
    seed: u32,
    size: usize,
}

// test/parity/inputs.ts, which the recorder used: xorshift32 from the same seed.
fn generate(input: &Input) -> Vec<u8> {
    let mut state = if input.seed == 0 { 1 } else { input.seed };
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        state
    };

    match input.generator.as_str() {
        "bytes" => (0..input.size).map(|_| next() as u8).collect(),
        "ascii" => (0..input.size)
            .map(|_| (PRINTABLE_START + next() % PRINTABLE_COUNT) as u8)
            .collect(),
        "lines" => {
            let mut out = Vec::with_capacity(input.size);
            while out.len() < input.size {
                let word = LINE_WORDS[next() as usize % LINE_WORDS.len()];
                let (line, column, arity) = (next() % 900, next() % 900, next() % 7);
                let name = char::from(b'a' + (next() % 26) as u8);
                let text = format!("    {line}:{column}:{word} {word}({arity}) -> {name}\n");
                let room = input.size - out.len();
                out.extend(text.bytes().take(room));
            }
            out
        }
        other => panic!("unknown generator {other}"),
    }
}

fn container(kind: &str, data: Vec<u8>) -> Vec<u8> {
    let text = |data: Vec<u8>| String::from_utf8(data).expect("generated text is UTF-8");

    match kind {
        "proguard" => write_symbol_data(ProguardMapping {
            content: text(data),
        }),
        "hermes" => write_symbol_data(HermesMap {
            sourcemap: text(data),
        }),
        "dsym" => write_symbol_data(AppleDsym { data }),
        "elf" => write_symbol_data(ElfDebugInfo { data }),
        other => panic!("unknown container type {other}"),
    }
    .expect("the container is written")
}

#[test]
fn containers_match_posthog_cli_byte_for_byte() {
    let cases: Vec<Case> = serde_json::from_str(GOLDEN).expect("the goldens parse");
    assert!(!cases.is_empty());

    for case in cases {
        let bytes = container(&case.r#type, generate(&case.input));

        assert_eq!(
            content_hash([&bytes]),
            case.hash,
            "{} {} {} bytes",
            case.r#type,
            case.input.generator,
            case.input.size
        );
    }
}
