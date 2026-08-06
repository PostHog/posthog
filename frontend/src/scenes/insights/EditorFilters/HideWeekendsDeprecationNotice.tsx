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
            The "Hide weekend data" option is deprecated. To exclude weekends, use the "Exclude" option in the date
            filter instead.
        </LemonBanner>
    )
}
