import { describe, expect, test } from 'bun:test'

import { dwarf4Object, op } from './dwarf-fixture'
import { BufferSource } from './object'
import { extractSourcePaths } from './walk'

const MAX = (1n << 64n) - 1n
const HEADER_FILES = ['/src/proj/include/util.h', '/src/proj/main.c']

// The expected paths come from posthog-cli's extract_source_paths (symbolic) on the same bytes.
describe('DW_LNE_define_file', () => {
    test.each([
        [
            'adds files the program defines',
            [
                ...op.setAddress(0x1000n),
                ...op.defineFile('defined.c', 0),
                ...op.copy,
                ...op.defineFile('extra.h', 1),
                ...op.endSequence,
            ],
            ['/src/proj/defined.c', '/src/proj/include/extra.h'],
        ],
        [
            'stops at the first address overflow',
            [
                ...op.setAddress(MAX - 0x10n),
                ...op.defineFile('before.c', 0),
                ...op.advancePc(0x20n),
                ...op.defineFile('after.c', 0),
            ],
            ['/src/proj/before.c'],
        ],
        [
            'skips address arithmetic after a tombstone address',
            [
                ...op.setAddress(0x2000n),
                ...op.copy,
                ...op.setAddress(0x10n),
                ...op.advancePc(MAX),
                ...op.defineFile('tomb.c', 0),
            ],
            ['/src/proj/tomb.c'],
        ],
        [
            'resets the address after an end of sequence',
            [...op.setAddress(MAX - 0x10n), ...op.endSequence, ...op.advancePc(0x20n), ...op.defineFile('reset.c', 0)],
            ['/src/proj/reset.c'],
        ],
        [
            'keeps the files defined before a truncated instruction',
            [...op.setAddress(0x1000n), ...op.defineFile('ok.c', 0), 0, 0x7f, 0x03],
            ['/src/proj/ok.c'],
        ],
    ])('%s', (_name, program, defined) => {
        const paths = extractSourcePaths(new BufferSource(dwarf4Object(program)))
        expect(paths).toEqual([...HEADER_FILES, ...defined].sort())
    })
})
