import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { LemonSwitch } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'

export function SamplingFilter({ filters: editorFilters }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(insightLogic)
    const { filters } = useValues(insightLogic)

    if (editorFilters.insight !== InsightType.LIFECYCLE) {
        return <></>
    }
    return (
        <>
            <div className="SamplingFilter">
                <LemonSwitch
                    checked={!!filters.sample_results}
                    label={
                        <>
                            <span>Turn on sampling</span>
                        </>
                    }
                    onChange={(newChecked) => setFilters({ ...filters, sample_results: newChecked })}
                />
            </div>
        </>
    )
}
