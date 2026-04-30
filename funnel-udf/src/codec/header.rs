// RowBinaryWithNamesAndTypes block header: varint n_cols, n_cols names, n_cols type strings.

use clickhouse_types::{Column, DataTypeNode};

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};

// Skips a block header off the wire without allocating Strings or building
// `DataTypeNode` trees. The columns sent in every chunk in an executable_pool
// process are identical (ClickHouse's schema for a given UDF is fixed for the
// lifetime of the process), so after the first chunk we cache the parsed
// columns and use this skipper for the rest. Eliminates ~8 String/Replace/
// DataTypeNode::new per chunk — the dominant per-call overhead at the
// production tiny-call shape.
//
// Uses a stack scratch buffer so typical short names/types skip with zero
// heap allocation. Falls back to a heap Vec for unusually long type strings.
pub fn skip_block_header<R: RowBinaryRead + ?Sized>(r: &mut R) -> CodecResult<()> {
    let n = r.read_varint()? as usize;
    let mut scratch = [0u8; 256];
    for _ in 0..(2 * n) {
        let len = r.read_varint()? as usize;
        if len <= scratch.len() {
            r.read_exact(&mut scratch[..len])?;
        } else {
            let mut big = vec![0u8; len];
            r.read_exact(&mut big)?;
        }
    }
    Ok(())
}

pub fn read_block_header<R: RowBinaryRead + ?Sized>(r: &mut R) -> CodecResult<Vec<Column>> {
    let n = r.read_varint()? as usize;
    let mut names = Vec::with_capacity(n);
    for _ in 0..n {
        names.push(String::from_utf8_lossy(&r.read_bytes()?).into_owned());
    }
    let mut types = Vec::with_capacity(n);
    for _ in 0..n {
        let type_str = String::from_utf8_lossy(&r.read_bytes()?).into_owned();
        // ClickHouse emits `Array(Nothing)` for a bare `[]` literal (no element
        // context), and `clickhouse-types` can't parse Nothing. The array length
        // is always 0, so the element type we substitute is never read.
        let normalized = type_str.replace("Array(Nothing)", "Array(Int8)");
        let node = DataTypeNode::new(&normalized)
            .map_err(|e| CodecError::UnknownType(format!("{type_str:?}: {e}")))?;
        types.push(node);
    }
    Ok(names
        .into_iter()
        .zip(types)
        .map(|(name, data_type)| Column::new(name, data_type))
        .collect())
}

pub fn write_block_header<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    columns: &[Column],
) -> CodecResult<()> {
    w.write_varint(columns.len() as u64)?;
    for c in columns {
        w.write_bytes(c.name.as_bytes())?;
    }
    for c in columns {
        w.write_bytes(c.data_type.to_string().as_bytes())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn header_roundtrip() {
        let cols = vec![
            Column::new("num_steps".into(), DataTypeNode::UInt8),
            Column::new(
                "value".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                    DataTypeNode::Nullable(Box::new(DataTypeNode::Float64)),
                    DataTypeNode::UUID,
                    DataTypeNode::Nullable(Box::new(DataTypeNode::String)),
                    DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
                ]))),
            ),
        ];
        let mut buf = Vec::new();
        write_block_header(&mut buf, &cols).unwrap();

        let mut slice = buf.as_slice();
        let parsed = read_block_header(&mut slice).unwrap();
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0].name, "num_steps");
        assert_eq!(parsed[0].data_type, DataTypeNode::UInt8);
        assert_eq!(parsed[1].name, "value");
    }

    #[test]
    fn header_normalizes_array_nothing() {
        let mut buf = Vec::new();
        buf.write_varint(1).unwrap();
        buf.write_bytes(b"optional_steps").unwrap();
        buf.write_bytes(b"Array(Nothing)").unwrap();
        let mut slice = buf.as_slice();
        let cols = read_block_header(&mut slice).unwrap();
        assert_eq!(
            cols[0].data_type,
            DataTypeNode::Array(Box::new(DataTypeNode::Int8))
        );
    }

    #[test]
    fn header_preserves_nothing_outside_array() {
        let mut buf = Vec::new();
        buf.write_varint(1).unwrap();
        buf.write_bytes(b"kind").unwrap();
        buf.write_bytes(b"Enum8('Nothing' = 1, 'Something' = 2)")
            .unwrap();
        let mut slice = buf.as_slice();
        let cols = read_block_header(&mut slice).unwrap();
        match &cols[0].data_type {
            DataTypeNode::Enum(_, values) => {
                assert!(values.values().any(|v| v == "Nothing"));
            }
            other => panic!("expected Enum, got {other:?}"),
        }
    }
}
