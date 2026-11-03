//! An ordered map that iterates keys in the same order as JavaScript objects.
//!
//! JavaScript puts array-index keys ("0", "12", ...) first in ascending numeric order.
//! All other string keys follow in insertion order. Replacing a value keeps its position.
//! Kea iterates reducer trees with `Object.keys`, so the order changes which reducer runs first
//! and the key order of the state objects. This map keeps the same order.

use std::collections::BTreeMap;

/// Returns the numeric value if `key` is a canonical JavaScript array index.
pub fn array_index(key: &str) -> Option<u32> {
    let bytes = key.as_bytes();
    if bytes.is_empty() || bytes.len() > 10 {
        return None;
    }
    if bytes.len() > 1 && bytes[0] == b'0' {
        return None;
    }
    if !bytes.iter().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let value: u64 = key.parse().ok()?;
    // The largest array index is 2^32 - 2.
    if value < 4_294_967_295 {
        Some(value as u32)
    } else {
        None
    }
}

pub struct OMap<V> {
    indexed: BTreeMap<u32, (String, V)>,
    named: Vec<(String, V)>,
}

impl<V> Default for OMap<V> {
    fn default() -> Self {
        OMap { indexed: BTreeMap::new(), named: Vec::new() }
    }
}

impl<V> OMap<V> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.indexed.len() + self.named.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn get(&self, key: &str) -> Option<&V> {
        match array_index(key) {
            Some(i) => self.indexed.get(&i).map(|(_, v)| v),
            None => self.named.iter().find(|(k, _)| k == key).map(|(_, v)| v),
        }
    }

    pub fn get_mut(&mut self, key: &str) -> Option<&mut V> {
        match array_index(key) {
            Some(i) => self.indexed.get_mut(&i).map(|(_, v)| v),
            None => self.named.iter_mut().find(|(k, _)| k == key).map(|(_, v)| v),
        }
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    /// Sets a value. An existing key keeps its position, like a JavaScript property assignment.
    /// Returns the previous value.
    pub fn insert(&mut self, key: String, value: V) -> Option<V> {
        match array_index(&key) {
            Some(i) => self.indexed.insert(i, (key, value)).map(|(_, v)| v),
            None => {
                if let Some(slot) = self.named.iter_mut().find(|(k, _)| *k == key) {
                    Some(std::mem::replace(&mut slot.1, value))
                } else {
                    self.named.push((key, value));
                    None
                }
            }
        }
    }

    pub fn remove(&mut self, key: &str) -> Option<V> {
        match array_index(key) {
            Some(i) => self.indexed.remove(&i).map(|(_, v)| v),
            None => {
                let pos = self.named.iter().position(|(k, _)| k == key)?;
                Some(self.named.remove(pos).1)
            }
        }
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &V)> {
        self.indexed
            .values()
            .map(|(k, v)| (k, v))
            .chain(self.named.iter().map(|(k, v)| (k, v)))
    }

    pub fn iter_mut(&mut self) -> impl Iterator<Item = (&String, &mut V)> {
        self.indexed
            .values_mut()
            .map(|(k, v)| (&*k, v))
            .chain(self.named.iter_mut().map(|(k, v)| (&*k, v)))
    }

    pub fn drain(&mut self) -> Vec<(String, V)> {
        let mut out: Vec<(String, V)> = std::mem::take(&mut self.indexed).into_values().collect();
        out.append(&mut self.named);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn index_keys_come_first_in_numeric_order() {
        let mut m = OMap::new();
        m.insert("b".into(), 1);
        m.insert("10".into(), 2);
        m.insert("a".into(), 3);
        m.insert("2".into(), 4);
        m.insert("01".into(), 5);
        let keys: Vec<&str> = m.iter().map(|(k, _)| k.as_str()).collect();
        assert_eq!(keys, vec!["2", "10", "b", "a", "01"]);
    }

    #[test]
    fn replace_keeps_position_and_remove_then_insert_moves_to_end() {
        let mut m = OMap::new();
        m.insert("a".into(), 1);
        m.insert("b".into(), 2);
        m.insert("a".into(), 3);
        assert_eq!(m.iter().map(|(k, v)| (k.as_str(), *v)).collect::<Vec<_>>(), vec![("a", 3), ("b", 2)]);
        m.remove("a");
        m.insert("a".into(), 4);
        assert_eq!(m.iter().map(|(k, _)| k.as_str()).collect::<Vec<_>>(), vec!["b", "a"]);
    }

    #[test]
    fn array_index_bounds() {
        assert_eq!(array_index("0"), Some(0));
        assert_eq!(array_index("4294967294"), Some(4294967294));
        assert_eq!(array_index("4294967295"), None);
        assert_eq!(array_index("-1"), None);
        assert_eq!(array_index(""), None);
        assert_eq!(array_index("1.5"), None);
    }
}
