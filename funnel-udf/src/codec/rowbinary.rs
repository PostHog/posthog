use std::io::{Read, Write};

use uuid::Uuid;

use crate::codec::{CodecError, CodecResult};

const VARINT_MAX_BYTES: usize = 10;

pub trait RowBinaryRead: Read {
    fn read_u8(&mut self) -> CodecResult<u8> {
        let mut b = [0u8; 1];
        self.read_exact(&mut b)?;
        Ok(b[0])
    }

    fn read_i8(&mut self) -> CodecResult<i8> {
        self.read_u8().map(|b| b as i8)
    }

    fn read_u16_le(&mut self) -> CodecResult<u16> {
        let mut b = [0u8; 2];
        self.read_exact(&mut b)?;
        Ok(u16::from_le_bytes(b))
    }

    fn read_u32_le(&mut self) -> CodecResult<u32> {
        let mut b = [0u8; 4];
        self.read_exact(&mut b)?;
        Ok(u32::from_le_bytes(b))
    }

    fn read_u64_le(&mut self) -> CodecResult<u64> {
        let mut b = [0u8; 8];
        self.read_exact(&mut b)?;
        Ok(u64::from_le_bytes(b))
    }

    fn read_f64_le(&mut self) -> CodecResult<f64> {
        let mut b = [0u8; 8];
        self.read_exact(&mut b)?;
        Ok(f64::from_le_bytes(b))
    }

    fn read_varint(&mut self) -> CodecResult<u64> {
        let mut acc: u64 = 0;
        for i in 0..VARINT_MAX_BYTES {
            let byte = self.read_u8()?;
            let shift = 7 * i as u32;
            if i == VARINT_MAX_BYTES - 1 && byte > 1 {
                return Err(CodecError::VarintOverflow);
            }
            acc |= ((byte & 0x7f) as u64) << shift;
            if byte & 0x80 == 0 {
                return Ok(acc);
            }
        }
        Err(CodecError::VarintOverflow)
    }

    // Strict UTF-8. Use only for protocol-controlled fields (e.g. attribution
    // type, order type) that are written by PostHog-side code and guaranteed
    // to be UTF-8. Wire-format identical to read_bytes.
    fn read_string(&mut self) -> CodecResult<String> {
        let buf = self.read_bytes()?;
        String::from_utf8(buf).map_err(|_| CodecError::InvalidUtf8)
    }

    // ClickHouse `String` is a byte-typed column. Use this for any value that
    // could originate from user data (event property, breakdown key, etc.);
    // enforcing UTF-8 there would crash on arbitrary bytes that CH stores
    // without complaint.
    fn read_bytes(&mut self) -> CodecResult<Vec<u8>> {
        let len = self.read_varint()? as usize;
        let mut buf = vec![0u8; len];
        self.read_exact(&mut buf)?;
        Ok(buf)
    }

    // ClickHouse stores UUID as two little-endian u64s: high half then low half.
    // uuid::Uuid's byte layout is big-endian per RFC 4122, so we do the swap here.
    fn read_uuid(&mut self) -> CodecResult<Uuid> {
        let hi = self.read_u64_le()?;
        let lo = self.read_u64_le()?;
        Ok(Uuid::from_u64_pair(hi, lo))
    }

    fn read_nullable<T, F>(&mut self, inner: F) -> CodecResult<Option<T>>
    where
        F: FnOnce(&mut Self) -> CodecResult<T>,
    {
        match self.read_u8()? {
            0 => Ok(Some(inner(self)?)),
            1 => Ok(None),
            b => Err(CodecError::InvalidNullMarker(b)),
        }
    }

    fn read_array<T, F>(&mut self, mut inner: F) -> CodecResult<Vec<T>>
    where
        F: FnMut(&mut Self) -> CodecResult<T>,
    {
        let len = self.read_varint()? as usize;
        let mut out = Vec::with_capacity(len);
        for _ in 0..len {
            out.push(inner(self)?);
        }
        Ok(out)
    }
}

impl<R: Read + ?Sized> RowBinaryRead for R {}

pub trait RowBinaryWrite: Write {
    fn write_u8(&mut self, v: u8) -> CodecResult<()> {
        self.write_all(&[v])?;
        Ok(())
    }

    fn write_i8(&mut self, v: i8) -> CodecResult<()> {
        self.write_u8(v as u8)
    }

    fn write_u32_le(&mut self, v: u32) -> CodecResult<()> {
        self.write_all(&v.to_le_bytes())?;
        Ok(())
    }

    fn write_u64_le(&mut self, v: u64) -> CodecResult<()> {
        self.write_all(&v.to_le_bytes())?;
        Ok(())
    }

    fn write_f64_le(&mut self, v: f64) -> CodecResult<()> {
        self.write_all(&v.to_le_bytes())?;
        Ok(())
    }

    fn write_varint(&mut self, mut v: u64) -> CodecResult<()> {
        loop {
            let b = (v & 0x7f) as u8;
            v >>= 7;
            if v == 0 {
                self.write_u8(b)?;
                return Ok(());
            }
            self.write_u8(b | 0x80)?;
        }
    }

    fn write_string(&mut self, s: &str) -> CodecResult<()> {
        self.write_bytes(s.as_bytes())
    }

    fn write_bytes(&mut self, b: &[u8]) -> CodecResult<()> {
        self.write_varint(b.len() as u64)?;
        self.write_all(b)?;
        Ok(())
    }

    fn write_uuid(&mut self, u: Uuid) -> CodecResult<()> {
        let (hi, lo) = u.as_u64_pair();
        self.write_u64_le(hi)?;
        self.write_u64_le(lo)?;
        Ok(())
    }

    fn write_nullable<T, F>(&mut self, value: Option<&T>, inner: F) -> CodecResult<()>
    where
        F: FnOnce(&mut Self, &T) -> CodecResult<()>,
    {
        match value {
            Some(v) => {
                self.write_u8(0)?;
                inner(self, v)
            }
            None => self.write_u8(1),
        }
    }

    fn write_array<T, F>(&mut self, items: &[T], mut inner: F) -> CodecResult<()>
    where
        F: FnMut(&mut Self, &T) -> CodecResult<()>,
    {
        self.write_varint(items.len() as u64)?;
        for item in items {
            inner(self, item)?;
        }
        Ok(())
    }
}

impl<W: Write + ?Sized> RowBinaryWrite for W {}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn roundtrip_varint(v: u64) {
        let mut buf = Vec::new();
        buf.write_varint(v).unwrap();
        let mut slice = buf.as_slice();
        assert_eq!(slice.read_varint().unwrap(), v);
    }

    #[rstest]
    #[case(0)]
    #[case(1)]
    #[case(127)]
    #[case(128)]
    #[case(16_383)]
    #[case(16_384)]
    #[case(u32::MAX as u64)]
    #[case(u64::MAX - 1)]
    #[case(u64::MAX)]
    fn varint_roundtrip(#[case] v: u64) {
        roundtrip_varint(v);
    }

    #[test]
    fn varint_overflow_on_11th_byte() {
        let buf = [0xff_u8; 11];
        let mut slice = buf.as_slice();
        let err = slice.read_varint().unwrap_err();
        matches!(err, CodecError::VarintOverflow);
    }

    #[test]
    fn string_roundtrip() {
        let long = "a".repeat(300);
        let cases: [&str; 4] = ["", "hello", long.as_str(), "∆π⚡️"];
        for s in cases {
            let mut buf = Vec::new();
            buf.write_string(s).unwrap();
            let mut slice = buf.as_slice();
            assert_eq!(slice.read_string().unwrap(), s);
        }
    }

    // UUID fixture: matches what ClickHouse emits for
    //   SELECT toUUID('01020304-0506-0708-090a-0b0c0d0e0f10') FORMAT RowBinary
    // i.e. 16 bytes that, when interpreted as two LE u64s (hi then lo), reproduce
    // the RFC 4122 UUID above.
    #[test]
    fn uuid_clickhouse_byte_order() {
        let u = Uuid::parse_str("01020304-0506-0708-090a-0b0c0d0e0f10").unwrap();
        let mut buf = Vec::new();
        buf.write_uuid(u).unwrap();
        // uuid as_u64_pair: hi = 0x0102030405060708, lo = 0x090a0b0c0d0e0f10
        // Little-endian hi on wire: 08 07 06 05 04 03 02 01
        // Little-endian lo on wire: 10 0f 0e 0d 0c 0b 0a 09
        assert_eq!(
            buf,
            vec![
                0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0x10, 0x0f, 0x0e, 0x0d, 0x0c, 0x0b,
                0x0a, 0x09,
            ]
        );

        let mut slice = buf.as_slice();
        let round = slice.read_uuid().unwrap();
        assert_eq!(round, u);
    }

    #[test]
    fn nullable_roundtrip() {
        let mut buf = Vec::new();
        buf.write_nullable(Some(&42u64), |w, v| w.write_u64_le(*v))
            .unwrap();
        buf.write_nullable::<u64, _>(None, |w, v| w.write_u64_le(*v))
            .unwrap();

        let mut slice = buf.as_slice();
        assert_eq!(slice.read_nullable(|r| r.read_u64_le()).unwrap(), Some(42));
        assert_eq!(
            slice.read_nullable(|r| r.read_u64_le()).unwrap(),
            None::<u64>
        );
    }

    #[test]
    fn nullable_invalid_marker() {
        let buf = [2u8];
        let mut slice = buf.as_slice();
        let err = slice.read_nullable(|r| r.read_u8()).unwrap_err();
        assert!(matches!(err, CodecError::InvalidNullMarker(2)));
    }

    #[test]
    fn array_roundtrip() {
        let items = [1i8, -5, 127, -128, 0];
        let mut buf = Vec::new();
        buf.write_array(&items, |w, v| w.write_i8(*v)).unwrap();
        let mut slice = buf.as_slice();
        let round: Vec<i8> = slice.read_array(|r| r.read_i8()).unwrap();
        assert_eq!(round, items);
    }

    #[test]
    fn nested_array_of_tuples_roundtrip() {
        // Array(Tuple(UInt64, Nullable(String), Array(Int8)))
        let tuples: Vec<(u64, Option<String>, Vec<i8>)> = vec![
            (1, Some("a".into()), vec![1, 2]),
            (2, None, vec![]),
            (3, Some(String::new()), vec![-1]),
        ];
        let mut buf = Vec::new();
        buf.write_array(&tuples, |w, (a, b, c)| {
            w.write_u64_le(*a)?;
            w.write_nullable(b.as_ref(), |w, s| w.write_string(s))?;
            w.write_array(c, |w, v| w.write_i8(*v))
        })
        .unwrap();

        let mut slice = buf.as_slice();
        let round: Vec<(u64, Option<String>, Vec<i8>)> =
            RowBinaryRead::read_array(&mut slice, |r| {
                let a = r.read_u64_le()?;
                let b = r.read_nullable(|r| r.read_string())?;
                let c = RowBinaryRead::read_array(r, |r| r.read_i8())?;
                Ok((a, b, c))
            })
            .unwrap();
        assert_eq!(round, tuples);
    }

    #[test]
    fn f64_nan_preserved_bitwise() {
        let mut buf = Vec::new();
        buf.write_f64_le(f64::NAN).unwrap();
        let mut slice = buf.as_slice();
        let round = slice.read_f64_le().unwrap();
        assert!(round.is_nan());
    }
}
