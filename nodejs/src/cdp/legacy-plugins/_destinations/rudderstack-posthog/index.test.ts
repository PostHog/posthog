import { parseJSON } from '~/common/utils/json-parse'

import { createEvent } from '../../test-utils'
import { onEvent, setupPlugin } from './index'

describe('RudderStack: onEvent', () => {
    const mockFetch = jest.fn()

    afterEach(() => {
        delete (Object.prototype as any).extra
        delete (Object.prototype.toString as any).extra
    })

    test.each(['__proto__.extra', 'constructor.prototype.extra', 'toString.extra'])(
        'keeps a dotted property key %s on the payload only',
        async (propKey) => {
            const meta: any = {
                config: { dataPlaneUrl: 'https://rudder.example.com/v1/batch', writeKey: 'test-write-key' },
                global: {},
                fetch: mockFetch,
            }
            await setupPlugin(meta)

            await onEvent(createEvent({ event: 'signed_up', properties: { [propKey]: 'yes', plan: 'free' } }), meta)

            expect(({} as any).extra).toBeUndefined()
            expect((Object.prototype.toString as any).extra).toBeUndefined()
            const body = parseJSON(mockFetch.mock.calls.at(-1)[1].body)
            expect(body.batch[0].properties.plan).toEqual('free')
        }
    )
})
