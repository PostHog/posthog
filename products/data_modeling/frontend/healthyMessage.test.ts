import { OverviewChecksStatus } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { healthyMessage } from './healthyMessage'

describe('healthyMessage', () => {
    it.each<[OverviewChecksStatus, boolean, string]>([
        ['all-passed', false, 'No failed, suspended or late models. All checks passed.'],
        [
            'some-not-passed',
            false,
            "No failed, suspended or late models. No checks are failing. Some haven't passed yet.",
        ],
        ['none', false, 'No failed, suspended or late models.'],
        ['unknown', true, 'No failed, suspended or late models. No failing checks among the first 500.'],
    ])('with checks %s and truncated=%s says only what was checked', (status, truncated, expected) => {
        expect(healthyMessage(status, truncated)).toEqual(expected)
    })
})
