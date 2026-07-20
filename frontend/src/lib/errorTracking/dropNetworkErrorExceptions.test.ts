import { dropNetworkErrorExceptions } from './dropNetworkErrorExceptions'

describe('dropNetworkErrorExceptions', () => {
    it('passes through non-exception events untouched', () => {
        const event = { event: '$pageview', properties: {} }
        expect(dropNetworkErrorExceptions(event)).toBe(event)
    })

    it('passes through exceptions that are not network errors', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'SyntaxError' }] },
        }
        expect(dropNetworkErrorExceptions(event)).toBe(event)
    })

    it('drops exceptions whose chain contains a NetworkError', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'NetworkError' }, { type: 'TypeError' }] },
        }
        expect(dropNetworkErrorExceptions(event)).toBeNull()
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropNetworkErrorExceptions(null)).toBeNull()
    })
})
