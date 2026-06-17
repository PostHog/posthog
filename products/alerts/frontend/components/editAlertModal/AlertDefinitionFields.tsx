import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { FunnelAlertPreview } from 'lib/components/Alerts/funnelAlertPreview'
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

/** A read-out of the conversion rate the funnel alert would evaluate right now, so the threshold
 * can be set against a real value before the first check. */
function FunnelAlertPreviewBanner({ preview }: { preview: FunnelAlertPreview | null }): JSX.Element | null {
    if (preview === null) {
        return null
    }
    if (preview.status === 'no-data') {
        return (
            <LemonBanner type="info" className="w-full">
                This funnel has no data for the selected steps yet, so the alert can't evaluate a conversion rate until
                it does.
            </LemonBanner>
        )
    }
    const format = (rate: number): string => `${rate.toFixed(1)}%`
    if (preview.isBreakdown) {
        const min = Math.min(...preview.rates)
        const max = Math.max(...preview.rates)
        return (
            <LemonBanner type="info" className="w-full">
                Across {preview.rates.length} breakdown values, conversion is currently{' '}
                <strong>
                    {format(min)}–{format(max)}
                </strong>{' '}
                — the alert fires if any value breaches the threshold.
            </LemonBanner>
        )
    }
    return (
        <LemonBanner type="info" className="w-full">
            This funnel currently converts at <strong>{format(preview.rates[0])}</strong> — the alert checks this
            against your threshold.
        </LemonBanner>
    )
}

/** Funnels: pick the conversion metric and step. */
export function FunnelsDefinitionFields({
    funnelStepCount,
    funnelPreview,
}: {
    funnelStepCount: number
    funnelPreview: FunnelAlertPreview | null
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-3 items-center">
            <div>Alert on</div>
            <Group name={['config']}>
                <LemonField name="metric" className="flex-auto">
                    <LemonSelect
                        fullWidth
                        data-attr="alertForm-funnel-metric"
                        options={[
                            { label: 'conversion from first step', value: 'conversion_from_start' },
                            { label: 'conversion from previous step', value: 'conversion_from_previous' },
                        ]}
                    />
                </LemonField>
                <LemonField name="funnel_step" className="flex-auto">
                    <LemonSelect
                        fullWidth
                        data-attr="alertForm-funnel-step"
                        options={[
                            { label: 'overall (last step)', value: null },
                            ...Array.from({ length: funnelStepCount }, (_, index) => ({
                                label: `step ${index + 1}`,
                                value: index,
                            })),
                        ]}
                    />
                </LemonField>
            </Group>
            <FunnelAlertPreviewBanner preview={funnelPreview} />
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
                                    // Any-row mode checks unrelated rows — a relative condition is meaningless.
                                    if (newValue === 'any_row') {
                                        onSetAlertFormValue('condition', { type: AlertConditionType.ABSOLUTE_VALUE })
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
