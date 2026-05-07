use serde::{ser::Error as _, Deserialize, Deserializer, Serialize, Serializer};

// ClickHouse `String` is byte-typed, not UTF-8. Breakdown values are Vec<u8>
// end-to-end; the newtype lets PropVal keep its derive while still round-tripping
// a JSON string on the debug path.
#[derive(Debug, Clone, PartialEq)]
pub struct Bytes(pub Vec<u8>);

impl<'de> Deserialize<'de> for Bytes {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Ok(Bytes(String::deserialize(d)?.into_bytes()))
    }
}

impl Serialize for Bytes {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        // Only reached on the JSON path, where bytes originated from a JSON string.
        std::str::from_utf8(&self.0)
            .map_err(S::Error::custom)?
            .serialize(s)
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum PropVal {
    String(Bytes),
    Vec(Vec<Bytes>),
    Int(u64),
    VecInt(Vec<u64>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakdownShape {
    NullableString,
    ArrayString,
    U64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(r#""hello""#, PropVal::String(Bytes(b"hello".to_vec())))]
    #[case(r#"42"#, PropVal::Int(42))]
    #[case(r#"4503599627370496"#, PropVal::Int(4503599627370496))] // 2^52 (NOT_IN_COHORT_ID)
    #[case(r#"["a","b"]"#, PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())]))]
    #[case(r#"[1, 2, 3]"#, PropVal::VecInt(vec![1, 2, 3]))]
    #[case(r#"[4503599627370496]"#, PropVal::VecInt(vec![4503599627370496]))]
    fn test_propval_deserialization(#[case] json: &str, #[case] expected: PropVal) {
        let result: PropVal = serde_json::from_str(json).unwrap();
        assert_eq!(result, expected);
    }
}
