use serde::{Deserialize, Deserializer, Serialize, Serializer};

// CH `String` is byte-typed, not UTF-8. Breakdown values are Vec<u8> end-to-end;
// the newtype exists so PropVal can keep its derive while still round-tripping a
// JSON string in the debug path.
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
        std::str::from_utf8(&self.0).unwrap().serialize(s)
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
