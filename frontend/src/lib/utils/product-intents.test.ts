import * as osFrame from 'scenes/os/bridge/osFrame'

import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { addProductIntent, addProductIntentForCrossSell } from './product-intents'

describe('product-intents', () => {
    let requests: number

    beforeEach(() => {
        requests = 0
        useMocks({
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => {
                    requests += 1
                    return [200, {}]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        [
            'an intent',
            () =>
                addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEYS_VIEWED,
                }),
        ],
        [
            'a cross-sell intent',
            () =>
                addProductIntentForCrossSell({
                    from: ProductKey.SURVEYS,
                    to: ProductKey.FEATURE_FLAGS,
                    intent_context: ProductIntentContext.SURVEYS_VIEWED,
                }),
        ],
    ])('sends %s, except from an app previewed in an OS window', async (_, send) => {
        await send()
        expect(requests).toBe(1)

        jest.spyOn(osFrame, 'isOsPreviewFrame').mockReturnValue(true)
        await expect(send()).resolves.toBeNull()
        expect(requests).toBe(1)
    })
})
