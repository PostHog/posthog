import { dropResponseBodyReadExceptions } from './dropResponseBodyReadExceptions'

describe('dropResponseBodyReadExceptions', () => {
    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/foo' } }
        expect(dropResponseBodyReadExceptions(event)).toBe(event)
    })

    it('passes $exception events without ResponseBodyReadError through', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'TypeError', value: 'x is not a function' }],
            },
        }
        expect(dropResponseBodyReadExceptions(event)).toBe(event)
    })

    it('drops $exception events whose top-level type is ResponseBodyReadError', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'ResponseBodyReadError', value: 'Failed to read response body' }],
            },
        }
        expect(dropResponseBodyReadExceptions(event)).toBeNull()
    })

    it('drops wrapped errors where ResponseBodyReadError lives in the cause chain', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'projectTreeLogic: assureVisibility failed' },
                    { type: 'ResponseBodyReadError', value: 'Failed to read response body' },
                ],
            },
        }
        expect(dropResponseBodyReadExceptions(event)).toBeNull()
    })

    it('returns null when handed null', () => {
        expect(dropResponseBodyReadExceptions(null)).toBeNull()
    })
})
