import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInputSelect, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { biEditorLogic } from './biEditorLogic'
import { getBIFieldPillLabel } from './biEditorTypes'
import { BI_PANE_CHART_TYPES } from './biPaneConfig'

export function BIPaneControls(): JSX.Element | null {
    const { config } = useValues(biEditorLogic)
    const { setPanes } = useActions(biEditorLogic)
    if (!BI_PANE_CHART_TYPES.includes(config.chartType)) {
        return null
    }
    const fields = [...config.rows, ...config.columns]
    return (
        <div className="mt-3 flex min-w-0 flex-col gap-2" data-attr="bi-pane-controls">
            <LemonLabel>Separate panes by</LemonLabel>
            <LemonInputSelect
                mode="multiple"
                value={config.panes?.fields ?? []}
                options={fields.map((field) => ({ key: field.id, label: getBIFieldPillLabel(field) }))}
                onChange={(selected) => setPanes(selected.length ? { ...config.panes, fields: selected } : undefined)}
                placeholder="Choose dimensions"
                allowCustomValues={false}
                sortable
                disabledReason={
                    fields.length < 2
                        ? 'Add at least two dimensions first'
                        : config.compareFilter?.compare
                          ? 'Turn off period comparison to use panes'
                          : undefined
                }
                limit={Math.max(0, fields.length - 1)}
                fullWidth
            />
            {!!config.panes?.fields.length && (
                <>
                    <p className="m-0 text-xs text-secondary">
                        Each dimension combination gets its own chart. Keep one axis dimension and, optionally, a color
                        dimension outside panes.
                    </p>
                    <LemonCheckbox
                        label="Independent value scales"
                        checked={!!config.panes.independentAxes}
                        onChange={(independentAxes) => setPanes({ ...config.panes!, independentAxes })}
                    />
                    <LemonLabel>Reference line calculations</LemonLabel>
                    <LemonSelect
                        size="xsmall"
                        fullWidth
                        value={config.panes.referenceLines ?? 'pane'}
                        options={[
                            { value: 'pane', label: 'Within each pane' },
                            { value: 'worksheet', label: 'Across the worksheet' },
                        ]}
                        onChange={(referenceLines) => setPanes({ ...config.panes!, referenceLines })}
                    />
                </>
            )}
        </div>
    )
}
