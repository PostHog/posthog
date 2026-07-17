import { readFileSync } from 'fs'
import path from 'path'

import { DEFAULT_TEXT_WORDS, DEFAULT_URL_SEGMENTS } from './default-dict'

// The single source of truth for the default allow lists is the `.txt` pair in the
// posthog-replay-anonymizer Rust crate (embedded there via include_str!). This test reads those
// data files and asserts the TS copy matches, so the ingestion (TS) and offline (Rust) pipelines
// can never drift to different default vocabularies. It reads the data files — it does not parse
// Rust source — so a rename/reformat on either side that changes no values leaves it green.
const RUST_CRATE_SRC = path.resolve(__dirname, '../../../../../../rust/replay-anonymizer/src')

function readEmbeddedList(file: string): string[] {
    return readFileSync(path.join(RUST_CRATE_SRC, file), 'utf8')
        .split('\n')
        .filter((line) => line.length > 0)
}

describe('anonymize/default-dict', () => {
    it('stays in sync with the Rust crate default lists', () => {
        expect(new Set(DEFAULT_TEXT_WORDS)).toEqual(new Set(readEmbeddedList('default_text_words.txt')))
        expect(new Set(DEFAULT_URL_SEGMENTS)).toEqual(new Set(readEmbeddedList('default_url_segments.txt')))
    })
})
