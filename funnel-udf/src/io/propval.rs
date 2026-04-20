use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::types::{BreakdownShape, Bytes, PropVal};

// Read a single breakdown value (event tuple position, or a result slot) in its
// shape-specific wire form.
//
// - NullableString: 1-byte null marker + varint + raw bytes. We expect non-null
//   in practice (funnel.py wraps prop_basic with ifNull(..., '')), so a null
//   marker is treated as a hard error — matches the behavior of the JSON path,
//   which has no PropVal variant for JSON null and would panic on it. Bytes
//   are read raw because ClickHouse `String` is byte-typed.
// - ArrayString: varint + N byte strings.
// - U64: 8 bytes LE.
pub fn read_propval<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
) -> CodecResult<PropVal> {
    match shape {
        BreakdownShape::NullableString => match r.read_nullable(|r| r.read_bytes())? {
            Some(b) => Ok(PropVal::String(Bytes(b))),
            None => Err(CodecError::UnexpectedNull),
        },
        BreakdownShape::ArrayString => {
            Ok(PropVal::Vec(r.read_array(|r| r.read_bytes().map(Bytes))?))
        }
        BreakdownShape::U64 => Ok(PropVal::Int(r.read_u64_le()?)),
    }
}

// Read a slot declared in the XML as Array(Nullable(String)) | Array(Array(String)) | Array(UInt64).
// This is the `prop_vals` argument and the output tuple's breakdown slot — each element is a PropVal.
pub fn read_propval_array<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
) -> CodecResult<Vec<PropVal>> {
    let len = r.read_varint()? as usize;
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        out.push(read_propval(r, shape)?);
    }
    Ok(out)
}

pub fn write_propval<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    p: &PropVal,
    shape: BreakdownShape,
) -> CodecResult<()> {
    match (shape, p) {
        (BreakdownShape::NullableString, PropVal::String(b)) => {
            w.write_u8(0)?; // non-null
            w.write_bytes(&b.0)
        }
        (BreakdownShape::ArrayString, PropVal::Vec(v)) => {
            w.write_array(v, |w, b| w.write_bytes(&b.0))
        }
        (BreakdownShape::U64, PropVal::Int(n)) => w.write_u64_le(*n),
        _ => Err(CodecError::ShapeMismatch),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nullable_string_roundtrip() {
        let mut buf = Vec::new();
        write_propval(
            &mut buf,
            &PropVal::String(Bytes(b"hi".to_vec())),
            BreakdownShape::NullableString,
        )
        .unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::NullableString).unwrap();
        assert_eq!(got, PropVal::String(Bytes(b"hi".to_vec())));
    }

    #[test]
    fn array_string_roundtrip() {
        let mut buf = Vec::new();
        write_propval(
            &mut buf,
            &PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())]),
            BreakdownShape::ArrayString,
        )
        .unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::ArrayString).unwrap();
        assert_eq!(
            got,
            PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())])
        );
    }

    // Regression: ClickHouse `String` can carry non-UTF-8 bytes (JSONEachRow used
    // to launder these; RowBinary hands them through raw). The reader must not
    // reject them.
    #[test]
    fn non_utf8_bytes_survive_roundtrip() {
        let bad = vec![0xff, 0xfe, 0x00, 0x80];
        let mut buf = Vec::new();
        write_propval(
            &mut buf,
            &PropVal::String(Bytes(bad.clone())),
            BreakdownShape::NullableString,
        )
        .unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::NullableString).unwrap();
        assert_eq!(got, PropVal::String(Bytes(bad)));
    }

    #[test]
    fn u64_roundtrip() {
        let mut buf = Vec::new();
        write_propval(&mut buf, &PropVal::Int(42), BreakdownShape::U64).unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::U64).unwrap();
        assert_eq!(got, PropVal::Int(42));
    }

    #[test]
    fn null_nullable_string_errors() {
        // Wire: null marker = 1
        let buf = vec![1u8];
        let mut slice = buf.as_slice();
        let err = read_propval(&mut slice, BreakdownShape::NullableString).unwrap_err();
        assert!(matches!(err, CodecError::UnexpectedNull));
    }

    #[test]
    fn shape_mismatch_errors() {
        let mut buf = Vec::new();
        let err =
            write_propval(&mut buf, &PropVal::Int(1), BreakdownShape::ArrayString).unwrap_err();
        assert!(matches!(err, CodecError::ShapeMismatch));
    }
}
