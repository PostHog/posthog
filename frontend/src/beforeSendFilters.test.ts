import { dropDevServerExceptions } from './beforeSendFilters'

describe('dropDevServerExceptions', () => {
    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/login' } }
        expect(dropDevServerExceptions(event)).toBe(event)
    })

    it('passes real $exception events through', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'TypeError', value: 'x is not a function' }],
            },
        }
        expect(dropDevServerExceptions(event)).toBe(event)
    })

    it('drops the Vite HMR error by message', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'Error', value: 'WebSocket closed without opened.' }],
            },
        }
        expect(dropDevServerExceptions(event)).toBeNull()
    })

    it('drops exceptions originating from the @vite/client module even without the known message', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    {
                        type: 'Error',
                        value: 'some other dev-server error',
                        stacktrace: {
                            frames: [{ function: 'createWebSocketModuleRunnerTransport', filename: '/@vite/client' }],
                        },
                    },
                ],
            },
        }
        expect(dropDevServerExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and missing exception list', () => {
        expect(dropDevServerExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropDevServerExceptions({ event: '$exception', properties: {} })).toEqual({
            event: '$exception',
            properties: {},
        })
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropDevServerExceptions(null)).toBeNull()
    })
})
