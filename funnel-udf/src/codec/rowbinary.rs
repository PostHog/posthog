use std::io::{Read, Write};

use uuid::Uuid;

use crate::codec::CodecResult;

const VARINT_MAX_BYTES: usize = 10;

pub trait RowBinaryRead: Read {
    /// Reads `N` bytes — the caller decodes them with the right `from_le_bytes`.
    fn read_le<const N: usize>(&mut self) -> CodecResult<[u8; N]> {
        let mut b = [0u8; N];
        self.read_exact(&mut b)?;
        Ok(b)
    }

    fn read_u8(&mut self) -> CodecResult<u8> {
        Ok(self.read_le::<1>()?[0])
    }

    fn read_u64_le(&mut self) -> CodecResult<u64> {
        Ok(u64::from_le_bytes(self.read_le()?))
    }

    fn read_f64_le(&mut self) -> CodecResult<f64> {
        Ok(f64::from_le_bytes(self.read_le()?))
    }

    fn read_varint(&mut self) -> CodecResult<u64> {
        let mut acc: u64 = 0;
        for i in 0..VARINT_MAX_BYTES {
            let byte = self.read_u8()?;
            acc |= ((byte & 0x7f) as u64) << (7 * i as u32);
            if byte & 0x80 == 0 {
                return Ok(acc);
            }
        }
        Err(crate::codec::CodecError::CorruptWire(format!(
            "varint exceeded {VARINT_MAX_BYTES} bytes (u64 max)"
        )))
    }

    // ClickHouse `String` is byte-typed: user-data fields (breakdown keys, event
    // properties) can hold arbitrary bytes. Protocol fields go through from_utf8_lossy
    // at the call site — never enforce UTF-8 here.
    fn read_bytes(&mut self) -> CodecResult<Vec<u8>> {
        let len = self.read_varint()? as usize;
        let mut buf = vec![0u8; len];
        self.read_exact(&mut buf)?;
        Ok(buf)
    }

    // ClickHouse writes UUID as two little-endian u64s (high half then low half),
    // not the RFC 4122 big-endian byte order that `uuid::Uuid` uses.
    fn read_uuid(&mut self) -> CodecResult<Uuid> {
        let hi = self.read_u64_le()?;
        let lo = self.read_u64_le()?;
        Ok(Uuid::from_u64_pair(hi, lo))
    }

    #[cfg(test)]
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
    fn varint_overflow_errors() {
        use crate::codec::CodecError;
        let buf = [0xff_u8; 11];
        let mut slice = buf.as_slice();
        match slice.read_varint() {
            Err(CodecError::CorruptWire(msg)) => assert!(msg.contains("varint exceeded")),
            other => panic!("expected CorruptWire, got {other:?}"),
        }
    }

    #[test]
    fn bytes_roundtrip() {
        let long = "a".repeat(300);
        let cases: [&[u8]; 4] = [b"", b"hello", long.as_bytes(), "∆π⚡️".as_bytes()];
        for s in cases {
            let mut buf = Vec::new();
            buf.write_bytes(s).unwrap();
            let mut slice = buf.as_slice();
            assert_eq!(slice.read_bytes().unwrap(), s);
        }
    }

    // Fixture pins ClickHouse's UUID byte order: two LE u64s (hi, lo).
    // This matches `SELECT toUUID('01020304-0506-0708-090a-0b0c0d0e0f10') FORMAT RowBinary`.
    #[test]
    fn uuid_clickhouse_byte_order() {
        let u = Uuid::parse_str("01020304-0506-0708-090a-0b0c0d0e0f10").unwrap();
        let mut buf = Vec::new();
        buf.write_uuid(u).unwrap();
        // hi=0x0102030405060708 LE: 08 07 06 05 04 03 02 01
        // lo=0x090a0b0c0d0e0f10 LE: 10 0f 0e 0d 0c 0b 0a 09
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
}
