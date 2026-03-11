import { LifecycleToggle } from '~/types'

import { getLifecycleTooltip } from './LifecycleToggles'

describe('getLifecycleTooltip', () => {
    it.each([
        [
            'new',
            { singular: 'person', plural: 'persons' },
            undefined,
            'Persons who did the event or action during the interval and were also created during that period, e.g. created an account and sent a message today.',
        ],
        [
            'returning',
            { singular: 'organization', plural: 'organizations' },
            0,
            'Organization that was active in the previous interval and is also active in the current interval, e.g. sent a message yesterday and also sent a message today.',
        ],
        [
            'resurrecting',
            { singular: 'company', plural: 'companies' },
            1,
            'Company that was not active in the previous interval but became active once again, e.g. did not send any messages for 10 days, but sent one today.',
        ],
        [
            'dormant',
            { singular: 'person', plural: 'persons' },
            undefined,
            'Persons who are not active in the current interval, but were active in the previous interval, e.g. did not send a message today, but sent one yesterday.',
        ],
    ])(
        'formats %s tooltip using the aggregation target',
        (lifecycle, aggregationTargetLabel, groupTypeIndex, expected) => {
            expect(getLifecycleTooltip(lifecycle as LifecycleToggle, aggregationTargetLabel, groupTypeIndex)).toEqual(
                expected
            )
        }
    )
})
