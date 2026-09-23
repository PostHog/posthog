import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { resolveScreenViewMode } from './screenViewMode'

describe('resolveScreenViewMode', () => {
    it.each([
        [undefined, false, null],
        [undefined, true, 'screens'],
        [{ webAnalyticsScreenViewMode: 'pageviews_and_screens' }, true, 'pageviews_and_screens'],
        [{ webAnalyticsScreenViewMode: 'pageviews' }, false, 'pageviews'],
    ] as [HogQLQueryModifiers | undefined, boolean, string | null][])(
        'team modifiers %j with mobile flag %s resolve to %s',
        (modifiers, mobileFlag, expected) => {
            expect(resolveScreenViewMode(modifiers, mobileFlag)).toEqual(expected)
        }
    )
})
