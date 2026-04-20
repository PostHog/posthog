use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::types::{BreakdownShape, PropVal};

// Read a single breakdown value (event tuple position, or a result slot) in its
// shape-specific wire form.
//
// - NullableString: 1-byte null marker + varint + string. We expect non-null in
//   practice (funnel.py wraps prop_basic with ifNull(..., '')), so a null marker
//   is treated as a hard error — matches the behavior of the current JSON path,
//   which has no PropVal variant for JSON null and would panic on it.
// - ArrayString: varint + N strings.
// - U64: 8 bytes LE.
pub fn read_propval<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
) -> CodecResult<PropVal> {
    match shape {
        BreakdownShape::NullableString => match r.read_nullable(|r| r.read_string())? {
            Some(s) => Ok(PropVal::String(s)),
            None => Err(CodecError::UnexpectedNull),
        },
        BreakdownShape::ArrayString => Ok(PropVal::Vec(r.read_array(|r| r.read_string())?)),
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
        (BreakdownShape::NullableString, PropVal::String(s)) => {
            w.write_u8(0)?; // non-null
            w.write_string(s)
        }
        (BreakdownShape::ArrayString, PropVal::Vec(v)) => {
            w.write_array(v, |w, s| w.write_string(s))
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
            &PropVal::String("hi".into()),
            BreakdownShape::NullableString,
        )
        .unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::NullableString).unwrap();
        assert_eq!(got, PropVal::String("hi".into()));
    }

    #[test]
    fn array_string_roundtrip() {
        let mut buf = Vec::new();
        write_propval(
            &mut buf,
            &PropVal::Vec(vec!["a".into(), "b".into()]),
            BreakdownShape::ArrayString,
        )
        .unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::ArrayString).unwrap();
        assert_eq!(got, PropVal::Vec(vec!["a".into(), "b".into()]));
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
