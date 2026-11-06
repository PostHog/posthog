//! Kafka messages that must equal the Node bytes use this writer, because `serde_json` prints `1.0` and `1e21`, not `1` and `1e+21`.

use std::fmt::Write;

use serde_json::Value;

pub fn write_value(out: &mut String, value: &Value) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => match n.as_f64() {
            Some(f) => write_number(out, f),
            None => out.push_str("null"),
        },
        Value::String(s) => write_string(out, s),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(out, item);
            }
            out.push(']');
        }
        Value::Object(map) => write_object(out, map.iter()),
    }
}

pub fn write_object<'a>(out: &mut String, entries: impl Iterator<Item = (&'a String, &'a Value)>) {
    let mut index_keys: Vec<(u32, &String, &Value)> = Vec::new();
    let mut other_keys: Vec<(&String, &Value)> = Vec::new();
    for (key, value) in entries {
        match array_index(key) {
            Some(index) => index_keys.push((index, key, value)),
            None => other_keys.push((key, value)),
        }
    }
    index_keys.sort_by_key(|(index, _, _)| *index);
    out.push('{');
    let ordered = index_keys
        .into_iter()
        .map(|(_, key, value)| (key, value))
        .chain(other_keys);
    for (i, (key, value)) in ordered.enumerate() {
        if i > 0 {
            out.push(',');
        }
        write_string(out, key);
        out.push(':');
        write_value(out, value);
    }
    out.push('}');
}

/// A canonical decimal below 2^32 - 1 is an array index, which a JavaScript object lists first.
fn array_index(key: &str) -> Option<u32> {
    if key.is_empty() || key.len() > 10 || !key.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    if key.len() > 1 && key.starts_with('0') {
        return None;
    }
    let value: u64 = key.parse().ok()?;
    (value < u32::MAX as u64).then_some(value as u32)
}

pub fn write_string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// JavaScript numbers are f64, so an integer above 2^53 prints as in Node.
pub fn write_number(out: &mut String, f: f64) {
    if !f.is_finite() {
        out.push_str("null");
        return;
    }
    if f == 0.0 {
        out.push('0');
        return;
    }
    if f < 0.0 {
        out.push('-');
    }
    let sci = shortest_scientific(f.abs());
    let (mantissa, exponent) = sci.split_once('e').expect("LowerExp has an exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let k = digits.len() as i32;
    let n = exponent.parse::<i32>().expect("integer exponent") + 1;
    if k <= n && n <= 21 {
        out.push_str(&digits);
        out.extend(std::iter::repeat_n('0', (n - k) as usize));
    } else if 0 < n && n <= 21 {
        out.push_str(&digits[..n as usize]);
        out.push('.');
        out.push_str(&digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', (-n) as usize));
        out.push_str(&digits);
    } else {
        out.push_str(&digits[..1]);
        if k > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let e = n - 1;
        let _ = write!(out, "e{}{}", if e >= 0 { "+" } else { "-" }, e.abs());
    }
}

/// ECMAScript breaks a tie between two shortest candidates toward even, so an odd last digit is checked against the exact rounding.
fn shortest_scientific(value: f64) -> String {
    let shortest = format!("{value:e}");
    let mantissa = shortest.split_once('e').map_or("", |(m, _)| m);
    let last_is_odd = mantissa.bytes().last().is_some_and(|d| (d - b'0') % 2 == 1);
    if !last_is_odd {
        return shortest;
    }
    let digits = mantissa.bytes().filter(u8::is_ascii_digit).count();
    let exact = format!("{:.*e}", digits - 1, value);
    // At a power of two the lower gap is narrower, so the nearest candidate can miss.
    if exact != shortest && exact.parse::<f64>() == Ok(value) {
        exact
    } else {
        shortest
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn number(f: f64) -> String {
        let mut out = String::new();
        write_number(&mut out, f);
        out
    }

    // Expected strings come from `String(x)` in Node 22.
    #[test]
    fn numbers_match_javascript() {
        let cases: &[(f64, &str)] = &[
            (1.0, "1"),
            (100.0, "100"),
            (-1.5, "-1.5"),
            (0.1, "0.1"),
            (-0.0, "0"),
            (1e21, "1e+21"),
            (1e20, "100000000000000000000"),
            (1.2345e-7, "1.2345e-7"),
            (0.000001, "0.000001"),
            (12345678901234567890.0, "12345678901234567000"),
            (5e-324, "5e-324"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (1e15 + 0.25, "1000000000000000.2"),
            (f64::from_bits(0x409a_ab1c_d000_0000), "1706.7781372070312"),
            (-1417389728594571.2, "-1417389728594571.2"),
        ];
        for (input, expected) in cases {
            assert_eq!(number(*input), *expected, "{input}");
        }
    }

    #[test]
    fn index_keys_come_first_like_a_javascript_object() {
        let mut map = indexmap::IndexMap::new();
        map.insert("b".to_string(), Value::from(1));
        map.insert("10".to_string(), Value::from(2));
        map.insert("2".to_string(), Value::from(3));
        map.insert("01".to_string(), Value::from(4));
        let mut out = String::new();
        write_object(&mut out, map.iter());
        assert_eq!(out, r#"{"2":3,"10":2,"b":1,"01":4}"#);
    }

    #[test]
    fn strings_escape_like_javascript() {
        let mut out = String::new();
        write_string(&mut out, "a\"\\/\u{7}\n\u{2028}é");
        assert_eq!(out, "\"a\\\"\\\\/\\u0007\\n\u{2028}é\"");
    }
}
