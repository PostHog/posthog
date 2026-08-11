import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function HideWeekendsDeprecationNotice({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))

    if (!trendsFilter?.hideWeekends) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="hide-weekends-deprecation-notice" className="m-2">
            The "Hide weekend data" option is being replaced by day-of-week exclusions in the date filter. They work a
            little differently: hiding weekends keeps weekend data in the calculation, excluding them leaves it out, so
            some numbers can differ.
        </LemonBanner>
    )
}
