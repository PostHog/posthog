use std::io::BufRead;
#[cfg(test)]
use std::io::Write;

use crate::codec::{CodecError, CodecResult};

// ClickHouse executable_pool with send_chunk_header=true prefixes each batch with
// a decimal row count and '\n'.
pub fn read_chunk_header<R: BufRead>(r: &mut R) -> CodecResult<Option<u64>> {
    let mut line = String::new();
    let n = r.read_line(&mut line)?;
    if n == 0 {
        return Ok(None); // true EOF — pool process shutting down
    }
    let trimmed = line.trim_end_matches(['\n', '\r']);
    if trimmed.is_empty() {
        // Blank line mid-stream: error instead of treating as EOF so we don't
        // silently drop the rest of the session.
        return Err(CodecError::InvalidChunkHeader(String::new()));
    }
    trimmed
        .parse::<u64>()
        .map(Some)
        .map_err(|_| CodecError::InvalidChunkHeader(trimmed.to_string()))
}

#[cfg(test)]
pub fn write_chunk_header<W: Write>(w: &mut W, n: u64) -> CodecResult<()> {
    writeln!(w, "{n}")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn eof_returns_none() {
        let mut r = Cursor::new(Vec::<u8>::new());
        assert!(read_chunk_header(&mut r).unwrap().is_none());
    }

    #[test]
    fn valid_count_parses() {
        let mut r = Cursor::new(b"42\n".to_vec());
        assert_eq!(read_chunk_header(&mut r).unwrap(), Some(42));
    }

    #[test]
    fn blank_line_errors_instead_of_silent_eof() {
        let mut r = Cursor::new(b"\n".to_vec());
        let err = read_chunk_header(&mut r).unwrap_err();
        assert!(matches!(err, CodecError::InvalidChunkHeader(_)));
    }

    #[test]
    fn malformed_count_errors() {
        let mut r = Cursor::new(b"not-a-number\n".to_vec());
        let err = read_chunk_header(&mut r).unwrap_err();
        assert!(matches!(err, CodecError::InvalidChunkHeader(_)));
    }
}
