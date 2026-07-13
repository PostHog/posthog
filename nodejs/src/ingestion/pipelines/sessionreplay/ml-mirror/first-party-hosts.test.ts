import { firstPartyHostPatterns } from './first-party-hosts'

describe('firstPartyHostPatterns reduces first-party url entries to registrable domains', () => {
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
