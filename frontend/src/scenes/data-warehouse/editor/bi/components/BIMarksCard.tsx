import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { biEditorLogic } from '../biEditorLogic'
import { getChartTypeOptions } from '../biEditorOptions'
import { BIShelfCard } from './BIShelfCard'

export function BIMarksCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { setChartType } = useActions(biEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <BIShelfCard title="Marks">
            <LemonSelect
                value={config.chartType}
                options={getChartTypeOptions(featureFlags).map((option) => ({
                    value: option.value,
                    label: option.label,
                    icon: option.icon,
                }))}
                onChange={setChartType}
                size="small"
                fullWidth
                aria-label="Mark type"
                data-attr="bi-editor-mark-type"
            />
            <span className="text-xs text-secondary">
                Measures on rows set the values. Change how a measure is calculated from its menu.
            </span>
        </BIShelfCard>
    )
}
