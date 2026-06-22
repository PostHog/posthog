import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { HogQLAlertPreview } from 'lib/components/Alerts/hogqlAlertPreview'
import { isAnyRowHogQLConfig } from 'lib/components/Alerts/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { alphabet } from 'lib/utils/strings'

import { AlertConditionType } from '~/queries/schema/schema-general'

import { HogQLAlertPreviewBanner, HogQLAlertPreviewRowsTable } from './HogQLAlertPreview'

const breakdownDisabledReason = (alertMode: 'detector' | 'threshold'): string =>
    alertMode === 'detector'
        ? 'For trends with breakdown, the detector will independently monitor each breakdown value (up to 25) and fire if any is anomalous.'
        : 'For trends with breakdown, the alert will fire if any of the breakdown values breaches the threshold.'

/** Trends: pick which series (or formula) to monitor. */
export function TrendsDefinitionFields({
    alertSeries,
    formulaNodes,
    isBreakdownValid,
    alertMode,
}: {
    alertSeries: Array<{ custom_name?: string | null; name?: string | null; event?: string | null }> | null
    formulaNodes: Array<{ formula: string; custom_name?: string | null }> | undefined
    isBreakdownValid: boolean
    alertMode: 'detector' | 'threshold'
}): JSX.Element {
    return (
        <div className="flex gap-3 items-center">
            <div>When</div>
            <Group name={['config']}>
                <LemonField name="series_index" className="flex-auto">
                    <LemonSelect
                        fullWidth
                        data-attr="alertForm-series-index"
                        options={
                            (formulaNodes?.length ?? 0) > 0
                                ? (formulaNodes ?? []).map(({ formula, custom_name }, index) => ({
                                      label: `${custom_name ? custom_name : 'Formula'} (${formula})`,
                                      value: index,
                                  }))
                                : (alertSeries?.map(({ custom_name, name, event }, index) => ({
                                      label: isBreakdownValid
                                          ? 'any breakdown value'
                                          : `${alphabet[index]} - ${custom_name ?? name ?? event}`,
                                      value: isBreakdownValid ? 0 : index,
                                  })) ?? [])
                        }
                        disabledReason={isBreakdownValid && breakdownDisabledReason(alertMode)}
                    />
                </LemonField>
            </Group>
        </div>
    )
}

/** SQL: pick the evaluation mode and (when the result is multi-column) the value/label columns,
 * plus the live preview of what the alert would evaluate. */
export function HogQLDefinitionFields({
    alertForm,
    hogqlPreview,
    hogqlColumns,
    hogqlValueColumnOptions,
    hogqlLabelColumnOptions,
    onSetAlertFormValue,
}: {
    alertForm: AlertFormType
    hogqlPreview: HogQLAlertPreview | null
    hogqlColumns: string[] | null
    hogqlValueColumnOptions: { label: string; value: string }[]
    hogqlLabelColumnOptions: { label: string; value: string }[]
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}): JSX.Element {
    const hasMultipleColumns = (hogqlColumns?.length ?? 0) > 1
    const isAnyRow = isAnyRowHogQLConfig(alertForm.config)
    return (
        <>
            <div className="flex gap-3 items-center">
                <div>When</div>
                <Group name={['config']}>
                    <LemonField name="evaluation" className="flex-auto">
                        {({ value, onChange }) => (
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-hogql-evaluation"
                                value={value ?? 'last_row'}
                                onChange={(newValue) => {
                                    onChange(newValue)
                                    // Any-row rows are unrelated entities, not a time series: a relative
                                    // condition has no prior value, and anomaly detection has nothing to
                                    // score. Reset both so we can't land in an unsupported any-row+detector
                                    // (or any-row+relative) state.
                                    if (newValue === 'any_row') {
                                        onSetAlertFormValue('condition', { type: AlertConditionType.ABSOLUTE_VALUE })
                                        onSetAlertFormValue('detector_config', null)
                                    }
                                }}
                                options={[
                                    {
                                        label: 'the last row',
                                        value: 'last_row',
                                        tooltip:
                                            'For queries ordered oldest→newest (the usual chart order): the last row is the current value.',
                                    },
                                    {
                                        label: 'the first row',
                                        value: 'first_row',
                                        tooltip:
                                            'For queries ordered newest→oldest (e.g. ORDER BY ... DESC): the first row is the current value. Pairs with a LIMIT to bound the query.',
                                    },
                                    {
                                        label: 'any row',
                                        value: 'any_row',
                                        tooltip:
                                            'Every row is checked and the alert fires if any value breaches the threshold — e.g. one row per country.',
                                    },
                                ]}
                            />
                        )}
                    </LemonField>
                    {hasMultipleColumns && (
                        <LemonField name="column" className="flex-auto">
                            {/* Prefilled with the last numeric column by alertFormLogic; the
                                placeholder only shows when nothing numeric is detectable. */}
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-hogql-column"
                                placeholder="select column to evaluate"
                                options={hogqlValueColumnOptions}
                            />
                        </LemonField>
                    )}
                </Group>
            </div>
            {isAnyRow && hasMultipleColumns && (
                <div className="flex gap-3 items-center">
                    <Tooltip title="Names the breaching row in notifications and the check history.">
                        <div className="flex items-center gap-1">
                            Labeled by <IconInfo className="text-muted" />
                        </div>
                    </Tooltip>
                    <Group name={['config']}>
                        <LemonField name="label_column" className="flex-auto">
                            {/* Prefilled with the first non-evaluated column by alertFormLogic. */}
                            <LemonSelect
                                fullWidth
                                data-attr="alertForm-hogql-label-column"
                                placeholder="select label column"
                                options={hogqlLabelColumnOptions}
                            />
                        </LemonField>
                    </Group>
                </div>
            )}
            <HogQLAlertPreviewBanner preview={hogqlPreview} conditionType={alertForm.condition?.type} />
            {hogqlPreview?.status === 'ok' && <HogQLAlertPreviewRowsTable preview={hogqlPreview} />}
        </>
    )
}
