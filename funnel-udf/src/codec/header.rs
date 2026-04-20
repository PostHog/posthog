// RowBinaryWithNamesAndTypes block header.
//
// Wire shape (emitted once per block, before any row data):
//   varint   n_columns
//   n_columns × String   column names
//   n_columns × String   column types (parsed into DataTypeNode by clickhouse-types)
//
// The executable-pool transport sits behind `send_chunk_header=true`, which
// adds a separate `N\n` *chunk* header before this block header (handled in
// codec::chunk).

use clickhouse_types::{put_leb128, Column, DataTypeNode};

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};

pub fn read_block_header<R: RowBinaryRead + ?Sized>(r: &mut R) -> CodecResult<Vec<Column>> {
    // We do the varint + length-prefixed string reads ourselves (same bits the
    // crate would use via `impl Buf`) and delegate just the type parsing to
    // `DataTypeNode::new` — that's the piece we don't want to re-implement.
    let n = r.read_varint()? as usize;
    let mut names = Vec::with_capacity(n);
    for _ in 0..n {
        names.push(String::from_utf8(r.read_bytes()?).map_err(|_| CodecError::InvalidUtf8)?);
    }
    let mut types = Vec::with_capacity(n);
    for _ in 0..n {
        let type_str = String::from_utf8(r.read_bytes()?).map_err(|_| CodecError::InvalidUtf8)?;
        let node = DataTypeNode::new(&type_str)
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
    // Use the crate's LEB128 writer to stay wire-compatible with its reader,
    // even though our write_varint is the same encoding.
    let mut leb_buf = Vec::with_capacity(10);

    put_leb128(&mut leb_buf, columns.len() as u64);
    w.write_all(&leb_buf)?;

    for c in columns {
        w.write_bytes(c.name.as_bytes())?;
    }
    for c in columns {
        let ty = c.data_type.to_string();
        w.write_bytes(ty.as_bytes())?;
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
}
