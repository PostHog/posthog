import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { todayLogic } from './todayLogic'

/** Says the page shows sample reports, so nobody mistakes them for the project's own. */
export function TodaySampleBanner(): JSX.Element | null {
    const { useSampleData } = useValues(todayLogic)
    const { setUseSampleData } = useActions(todayLogic)
    if (!useSampleData) {
        return null
    }
    return (
        <LemonBanner
            type="info"
            className="mb-8"
            action={{
                children: 'Show my reports',
                onClick: () => setUseSampleData(false),
                'data-attr': 'today-sample-data-off',
            }}
        >
            You’re looking at sample reports, not your project’s. They stay on until you turn them off.
        </LemonBanner>
    )
}
