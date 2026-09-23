import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'

describe('dataRetentionBannerLogic', () => {
    it.each([
        {
            name: 'reads the window from the events retention endpoint',
            response: [
                200,
                {
                    retention_months: 84,
                    retained_from: '2019-09-22',
                    docs_url: 'https://posthog.com/docs/data/events-retention',
                },
            ],
            retentionMonths: 84,
        },
        {
            name: 'treats a 404 as retention not enforced',
            response: [404, { detail: 'Not found.' }],
            retentionMonths: null,
        },
    ])('$name', async ({ response, retentionMonths }) => {
        useMocks({ get: { '/api/projects/:team_id/events_retention/': () => response } })
        initKeaTests()
        const logic = dataRetentionBannerLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadRetentionMonths', 'loadRetentionMonthsSuccess'])
            .toMatchValues({ retentionMonths, retentionEnforced: retentionMonths !== null })
    })
})
