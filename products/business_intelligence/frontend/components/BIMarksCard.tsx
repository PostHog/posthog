import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getBIFieldPillLabel, isDateTimeBIField } from 'products/business_intelligence/frontend/biEditorTypes'
import { BIShelfCard } from 'products/business_intelligence/frontend/components/BIShelfCard'

import { BIMeasureAnalysis } from '../BIMeasureAnalysis'

export function BIMarksCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { combineMeasures, setColorBy } = useActions(biEditorLogic)

    return (
        <BIShelfCard title="Series">
            <LemonLabel className="mt-2 text-xs">Color</LemonLabel>
            <LemonSelect
                value={config.colorBy === undefined ? '__automatic' : config.colorBy}
                options={[
                    { value: '__automatic', label: 'Automatic colors' },
                    { value: null, label: 'Single color' },
                    ...(config.rows.length + config.columns.length === 2 && !config.compareFilter?.compare
                        ? [...config.rows, ...config.columns]
                              .filter((field) => !isDateTimeBIField(field))
                              .map((field) => ({ value: field.id, label: `By ${getBIFieldPillLabel(field)}` }))
                        : []),
                ]}
                onChange={(colorBy) => setColorBy(colorBy === '__automatic' ? undefined : colorBy)}
                aria-label="Color series by"
                size="xsmall"
                fullWidth
                data-attr="bi-editor-color-by"
            />
            <span className="text-xs text-secondary">
                Shelves define the groups. Color changes how series are distinguished.
            </span>
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
