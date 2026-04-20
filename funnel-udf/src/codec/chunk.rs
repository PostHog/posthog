use std::io::{BufRead, Write};

use crate::codec::{CodecError, CodecResult};

// ClickHouse executable_pool with send_chunk_header = true prefixes each batch with
// a decimal row count followed by '\n', then sends that many rows in the configured
// format. On EOF (process about to exit) we read an empty line / EOF and return None.
pub fn read_chunk_header<R: BufRead>(r: &mut R) -> CodecResult<Option<u64>> {
    let mut line = String::new();
    let n = r.read_line(&mut line)?;
    if n == 0 {
        return Ok(None);
    }
    let trimmed = line.trim_end_matches(['\n', '\r']);
    if trimmed.is_empty() {
        return Ok(None);
    }
    trimmed
        .parse::<u64>()
        .map(Some)
        .map_err(|_| CodecError::InvalidChunkHeader(trimmed.to_string()))
}

pub fn write_chunk_header<W: Write>(w: &mut W, n: u64) -> CodecResult<()> {
    writeln!(w, "{n}")?;
    Ok(())
}
