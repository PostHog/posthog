import fs from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { firstPartyHostPatterns } from './first-party-hosts'

// Shared with the Rust `host_pattern` test so the two PSL reductions (tldts vs the psl crate)
// cannot drift on these cases.
const HOST_PATTERN_FIXTURE = path.resolve(
    __dirname,
    '../../../../../../rust/replay-anonymizer-node/tests/fixtures/host-pattern.json'
)

describe('firstPartyHostPatterns reduces first-party url entries to registrable domains', () => {
    const sharedCases: { name: string; input: string; expected: string | null }[] = parseJSON(
        fs.readFileSync(HOST_PATTERN_FIXTURE, 'utf8')
    )

    test.each(sharedCases.map((c) => [c.name, c] as const))('shared host-pattern case: %s', (_name, c) => {
        expect(firstPartyHostPatterns([c.input])).toEqual(c.expected === null ? [] : [c.expected])
    })

    test.each([
        ['subdomain and scheme dropped', ['https://www.example.com'], ['example.com']],
        ['deep subdomain dropped', ['https://app.eu.example.com'], ['example.com']],
        ['multi-part public suffix kept', ['https://www.example.co.uk'], ['example.co.uk']],
        ['wildcard entry reduces to its base', ['https://*.example.com'], ['example.com']],
        ['port and path dropped', ['https://app.example.com:5000/welcome'], ['example.com']],
        ['localhost kept whole', ['capacitor://localhost'], ['localhost']],
        ['ip kept whole', ['http://192.168.0.10:3000'], ['192.168.0.10']],
        ['bare wildcard ignored, casing normalized', ['*', 'https://App.Example.com'], ['example.com']],
        ['null and empty input give no patterns', null, []],
        ['private-suffix platform host keeps the tenant label', ['https://myapp.vercel.app'], ['myapp.vercel.app']],
        ['bare public suffix entries are dropped', ['https://*.com', 'https://co.uk'], []],
        ['non-string elements are skipped', [null as any, 'https://www.example.com'], ['example.com']],
        ['opaque-scheme host is lowercased', ['capacitor://LocalHost'], ['localhost']],
        [
            'entries reducing to the same domain dedupe',
            ['https://www.example.com', 'https://example.com/login'],
            ['example.com'],
        ],
    ] as [string, string[] | null, string[]][])('%s', (_name, domains, expected) => {
        expect(firstPartyHostPatterns(domains)).toEqual(expected)
    })
})
