import { readSessionSupportedClientTools } from './supported-client-tools'

describe('readSessionSupportedClientTools', () => {
    it('returns [] for null / undefined / missing key', () => {
        expect(readSessionSupportedClientTools(null)).toEqual([])
        expect(readSessionSupportedClientTools(undefined)).toEqual([])
        expect(readSessionSupportedClientTools({})).toEqual([])
        expect(readSessionSupportedClientTools({ client_kind: 'posthog-code' })).toEqual([])
    })

    it('returns the declared tool ids', () => {
        expect(readSessionSupportedClientTools({ supported_client_tools: ['connect_mcp', 'set_secret'] })).toEqual([
            'connect_mcp',
            'set_secret',
        ])
    })

    it('drops non-string / empty entries (defensive against untyped JSONB)', () => {
        expect(
            readSessionSupportedClientTools({ supported_client_tools: ['connect_mcp', 1, null, '', 'set_secret'] })
        ).toEqual(['connect_mcp', 'set_secret'])
    })

    it('returns [] when the stored value is not an array', () => {
        expect(readSessionSupportedClientTools({ supported_client_tools: 'connect_mcp' })).toEqual([])
    })
})
