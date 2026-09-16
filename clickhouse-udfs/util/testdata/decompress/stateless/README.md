# decompress Stateless Fixtures

The integration script also checks 10,000 mixed compressed/plain rows with short-circuit evaluation and 128-row chunks.

`truncated_frame.fail` rejects an LZ4 magic number without the rest of its frame, which the underlying reader otherwise accepts as empty output.

| Fixture               | Coverage                                                                                                                  |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `codecs`              | Explicit and automatic GZIP, ZSTD, and framed LZ4 decoding, plus raw and size-prefixed LZ4 blocks, across two-row chunks. |
| `binary`              | Every byte value, including NUL, newlines and invalid UTF-8, plus an empty decompressed string.                           |
| `size_mismatch.fail`  | Rejects a replay envelope whose size prefix differs from its decoded block length.                                        |
| `size_limit.fail`     | Rejects a replay envelope exceeding the output limit before allocating its output.                                        |
| `unknown_header.fail` | Rejects data without a recognized framed-codec header.                                                                    |
