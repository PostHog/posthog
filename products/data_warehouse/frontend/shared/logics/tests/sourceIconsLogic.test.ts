import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sourceIconsLogic } from '../sourceIconsLogic'

describe('sourceIconsLogic', () => {
    afterEach(() => {
        sourceIconsLogic.unmount()
    })

    it('loads the flat icon map on mount', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/source_icons': () => [
                    200,
                    { Stripe: '/static/services/stripe.png' },
                ],
            },
        })
        initKeaTests()
        sourceIconsLogic.mount()

        await expectLogic(sourceIconsLogic)
            .toDispatchActions(['loadSourceIconsSuccess'])
            .toMatchValues({ sourceIcons: { Stripe: '/static/services/stripe.png' } })
    })

    it('degrades a fetch failure to a null map instead of throwing from the mount hook', async () => {
        // SourceIcon mounts this on unrelated pages (e.g. the SQL editor), so a failed icon fetch must
        // never throw onto them — it falls back to the local icon map or renders nothing.
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/source_icons': () => [500, {}],
            },
        })
        initKeaTests()
        sourceIconsLogic.mount()

        await expectLogic(sourceIconsLogic)
            .toDispatchActions(['loadSourceIconsSuccess'])
            .toMatchValues({ sourceIcons: null })
    })
})
