// Strict column readers. Callers on the Python side cast every arg to the
// declared XML types before invoking the UDF, so the wire type must match
// exactly; any mismatch is a caller-side bug worth failing loudly on.

use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::RowBinaryRead;
use crate::codec::{CodecError, CodecResult};

pub fn read_u8_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<u8> {
    match t {
        DataTypeNode::UInt8 => r.read_u8(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected UInt8, got {other}"
        ))),
    }
}

pub fn read_u64_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<u64> {
    match t {
        DataTypeNode::UInt64 => r.read_u64_le(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected UInt64, got {other}"
        ))),
    }
}

/// Reads a `Nullable(Float64)` column, erroring if the value is actually NULL.
/// Funnel semantics: event timestamps are never null by the time they reach the UDF.
pub fn read_nullable_f64<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<f64> {
    match t {
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::Float64) => {
            match r.read_u8()? {
                0 => r.read_f64_le(),
                1 => Err(CodecError::UnexpectedNull),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Nullable(Float64), got {other}"
        ))),
    }
}

/// Reads a plain `String` column as raw bytes.
pub fn read_string<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<Vec<u8>> {
    match t {
        DataTypeNode::String => r.read_bytes(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected String, got {other}"
        ))),
    }
}

/// Reads a `Nullable(String)` column as raw bytes, erroring if actually NULL.
/// Funnel semantics: `ifNull(..., '')` upstream means nulls should never arrive.
pub fn read_nullable_string<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<u8>> {
    match t {
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::String) => {
            match r.read_u8()? {
                0 => r.read_bytes(),
                1 => Err(CodecError::UnexpectedNull),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Nullable(String), got {other}"
        ))),
    }
}

/// Reads an `Array(Int8)` column.
pub fn read_array_i8<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<i8>> {
    let inner = array_elem(t, "Array(Int8)")?;
    if !matches!(inner, DataTypeNode::Int8) {
        return Err(CodecError::TypeMismatch(format!(
            "expected Array(Int8), got Array({inner})"
        )));
    }
    let len = r.read_varint()? as usize;
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        out.push(r.read_i8()?);
    }
    Ok(out)
}

/// Extracts the element type from an `Array(T)`, erroring with context if `t` is not an Array.
pub fn array_elem<'a>(t: &'a DataTypeNode, ctx: &str) -> CodecResult<&'a DataTypeNode> {
    match t {
        DataTypeNode::Array(inner) => Ok(inner),
        other => Err(CodecError::TypeMismatch(format!(
            "{ctx}: expected Array(...), got {other}"
        ))),
    }
}

/// Extracts tuple field types, asserting the expected arity.
pub fn tuple_fields<'a>(
    t: &'a DataTypeNode,
    expected: usize,
    ctx: &str,
) -> CodecResult<&'a [DataTypeNode]> {
    match t {
        DataTypeNode::Tuple(fields) if fields.len() == expected => Ok(fields),
        DataTypeNode::Tuple(fields) => Err(CodecError::TypeMismatch(format!(
            "{ctx}: Tuple arity {} != expected {}",
            fields.len(),
            expected
        ))),
        other => Err(CodecError::TypeMismatch(format!(
            "{ctx}: expected Tuple, got {other}"
        ))),
    }
}

/// Reads a UUID from a `UUID` column.
pub fn read_uuid<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<uuid::Uuid> {
    match t {
        DataTypeNode::UUID => r.read_uuid(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected UUID, got {other}"
        ))),
    }
}
