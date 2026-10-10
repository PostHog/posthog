import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getChartTypeOptions } from 'products/business_intelligence/frontend/biEditorOptions'
import { BIShelfCard } from 'products/business_intelligence/frontend/components/BIShelfCard'

import { BIMeasureAnalysis } from '../BIMeasureAnalysis'

export function BIMarksCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { setChartType, combineMeasures } = useActions(biEditorLogic)
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
                size="xsmall"
                fullWidth
                aria-label="Mark type"
                data-attr="bi-editor-mark-type"
                tooltip="Change how measures on Rows are displayed"
            />
            {config.values.length === 2 ? (
                <LemonButton
                    size="xsmall"
                    fullWidth
                    data-attr="bi-editor-combine-measures"
                    onClick={combineMeasures}
                    disabledReason={
                        config.rows.length + config.columns.length > 2
                            ? 'Use at most two dimensions for a combined chart'
                            : undefined
                    }
                >
                    Combine line + bar
                </LemonButton>
            ) : null}
            {config.values.map((_, index) => (
                <BIMeasureAnalysis key={index} index={index} />
            ))}
        </BIShelfCard>
    )
}
