import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'

describe('dataRetentionBannerLogic', () => {
    let logic: ReturnType<typeof dataRetentionBannerLogic.build>

    afterEach(() => {
        logic.unmount()
        window.POSTHOG_APP_CONTEXT = undefined as unknown as AppContext
    })

    it.each([
        {
            description: 'reads the window the server bootstrapped',
            appContext: { events_retention_months: 84 },
            retentionMonths: 84,
            retentionEnforced: true,
        },
        {
            description: 'treats a missing window as not enforced',
            appContext: {},
            retentionMonths: null,
            retentionEnforced: false,
        },
    ])('$description', ({ appContext, retentionMonths, retentionEnforced }) => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = appContext as unknown as AppContext
        logic = dataRetentionBannerLogic()
        logic.mount()

        expect(logic.values.retentionMonths).toBe(retentionMonths)
        expect(logic.values.retentionEnforced).toBe(retentionEnforced)
    })
})
