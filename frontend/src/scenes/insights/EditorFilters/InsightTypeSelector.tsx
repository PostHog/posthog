import { useActions } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { EditorFilterProps } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'

export function InsightTypeSelector({ value }: EditorFilterProps): JSX.Element {
    const { setActiveView } = useActions(insightLogic)

    return (
        <LemonSelect
            options={INSIGHT_TYPE_OPTIONS}
            value={value}
            onChange={(v: any): void => {
                if (v) {
                    setActiveView(v)
                }
            }}
            fullWidth
            data-attr="insight-type"
        />
    )
}
