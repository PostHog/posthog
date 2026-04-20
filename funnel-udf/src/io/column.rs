// Type-tolerant column readers, driven by `DataTypeNode` from the block header.
//
// ClickHouse does NOT coerce UDF arguments to the XML-declared types — it
// sends the caller's native column type. To avoid wire drift (UInt32 literal
// in a UInt64 slot, `ifNull(..., '')` producing String where we declared
// Nullable(String), etc.), each reader takes the header's `DataTypeNode` and
// dispatches.

use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::RowBinaryRead;
use crate::codec::{CodecError, CodecResult};

/// Reads an unsigned integer column, widening to u64.
/// Accepts: UInt8, UInt16, UInt32, UInt64.
pub fn read_uint_as_u64<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<u64> {
    match t {
        DataTypeNode::UInt8 => Ok(r.read_u8()? as u64),
        DataTypeNode::UInt16 => Ok(r.read_u16_le()? as u64),
        DataTypeNode::UInt32 => Ok(r.read_u32_le()? as u64),
        DataTypeNode::UInt64 => r.read_u64_le(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected unsigned integer, got {other}"
        ))),
    }
}

/// Reads a `Float64` or `Nullable(Float64)` column, erroring on null.
/// (Funnel semantics: timestamps are never null by the time they reach the UDF.)
pub fn read_f64_nonnull<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<f64> {
    match t {
        DataTypeNode::Float64 => r.read_f64_le(),
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::Float64) => {
            match r.read_u8()? {
                0 => r.read_f64_le(),
                1 => Err(CodecError::UnexpectedNull),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Float64 / Nullable(Float64), got {other}"
        ))),
    }
}

/// Reads a `String` or `Nullable(String)` column as raw bytes, erroring on null.
/// (Funnel semantics: `ifNull(..., '')` upstream means nulls should never arrive.)
pub fn read_string_bytes_nonnull<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<u8>> {
    match t {
        DataTypeNode::String => r.read_bytes(),
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::String) => {
            match r.read_u8()? {
                0 => r.read_bytes(),
                1 => Err(CodecError::UnexpectedNull),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected String / Nullable(String), got {other}"
        ))),
    }
}

/// Reads an `Array(Int8)` column, tolerating `Array(Nothing)` isn't in this
/// crate's type AST — empty arrays arrive with a compatible scalar type.
pub fn read_array_i8<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<i8>> {
    let inner = array_elem(t, "Array(Int8)")?;
    let len = r.read_varint()? as usize;
    match inner {
        DataTypeNode::Int8 | DataTypeNode::UInt8 => {
            let mut out = Vec::with_capacity(len);
            for _ in 0..len {
                out.push(r.read_i8()?);
            }
            Ok(out)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Array(Int8), got Array({other})"
        ))),
    }
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
