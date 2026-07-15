import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { alphabet } from 'lib/utils/strings'

import { AlertConditionType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    funnelConfigForOptionKey,
    funnelConfigToOptionKey,
    funnelConversionOptions,
} from 'products/alerts/frontend/logic/funnelAlertOptions'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import { isFunnelsAlertConfig } from 'products/alerts/frontend/types'

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

// Cap the named breaching breakdown values so a high-cardinality breakdown can't produce a runaway
// banner string (mirrors the SQL preview's table cap); the rest collapse into "+N more".
const FUNNEL_BREACH_PREVIEW_CAP = 5

/** Conversion-rate read-out + breach/ok status (mirrors the SQL alert's preview). */
function FunnelAlertPreviewBanner({ preview }: { preview: FunnelAlertPreview | null }): JSX.Element | null {
    if (preview === null) {
        return (
            <LemonBanner type="info" className="w-full">
                Load the insight to preview the conversion rate this alert will evaluate.
            </LemonBanner>
        )
    }
    if (preview.status === 'no-data') {
        return (
            <LemonBanner type="info" className="w-full">
                This funnel has no data for the selected steps yet, so the alert can't evaluate a conversion rate. Try
                adjusting the funnel steps or the date range.
            </LemonBanner>
        )
    }
    const format = (rate: number): string => `${rate.toFixed(1)}%`
    const breaching = preview.values.filter((value) => value.breaching)
    const wouldFire = breaching.length > 0
    // Same at-a-glance breach/ok tag as the SQL alert preview; only meaningful once a threshold is set.
    const statusTag = preview.hasBounds ? (
        <LemonTag type={wouldFire ? 'warning' : 'success'} className="mr-2">
            {wouldFire ? 'breach' : 'ok'}
        </LemonTag>
    ) : null

    if (preview.relative) {
        // Relative alerts evaluate the change between the period being checked and the one before it
        // (the checkbox controls whether that's the in-progress period); `breaching` reflects the change.
        const first = preview.values[0]
        const hasPrior = preview.values.some((value) => value.previousRate !== undefined)
        return (
            <LemonBanner type={wouldFire ? 'warning' : 'info'} className="w-full">
                {statusTag}
                {!hasPrior ? (
                    <>Needs an earlier completed period to compare against — extend the date range.</>
                ) : preview.isBreakdown ? (
                    <>
                        Across {preview.values.length} breakdown values, comparing each period against the one before it
                        {wouldFire ? `: ${breaching.map((value) => value.label ?? 'conversion').join(', ')}` : ''}.
                    </>
                ) : (
                    <>
                        Evaluating <strong>{format(first.rate)}</strong> against{' '}
                        <strong>{format(first.previousRate as number)}</strong> (the prior period).
                    </>
                )}
                {!preview.hasBounds ? <> Set a threshold to preview whether it would fire.</> : null}
            </LemonBanner>
        )
    }

    if (preview.isBreakdown) {
        const rates = preview.values.map((value) => value.rate)
        return (
            <LemonBanner type={wouldFire ? 'warning' : 'info'} className="w-full">
                {statusTag}
                Across {preview.values.length} breakdown values, currently{' '}
                <strong>
                    {format(Math.min(...rates))}–{format(Math.max(...rates))}
                </strong>
                {/* The tag + banner colour carry the breach/ok state; only add what they can't — which
                    values breach, or (when no threshold is set yet) a prompt to set one. */}
                {!preview.hasBounds ? (
                    <> — fires if any value breaches. Set a threshold to preview.</>
                ) : wouldFire ? (
                    <>
                        {' '}
                        ·{' '}
                        {breaching
                            .slice(0, FUNNEL_BREACH_PREVIEW_CAP)
                            .map((value) => `${value.label ?? 'conversion'} ${format(value.rate)}`)
                            .join(', ')}
                        {breaching.length > FUNNEL_BREACH_PREVIEW_CAP
                            ? ` +${breaching.length - FUNNEL_BREACH_PREVIEW_CAP} more`
                            : ''}
                    </>
                ) : null}
            </LemonBanner>
        )
    }

    return (
        <LemonBanner type={wouldFire ? 'warning' : 'info'} className="w-full">
            {statusTag}
            Currently converting at <strong>{format(preview.values[0].rate)}</strong>
            {!preview.hasBounds ? <> — set a threshold to preview whether it would fire.</> : null}
        </LemonBanner>
    )
}

/** Funnels: a single valid-conversion picker over the `{metric, funnel_step}` config — see funnelAlertOptions.
 * A trends funnel charts the overall (whole-funnel) conversion rate over time, so there's no per-step
 * choice to make — it shows just the preview of the latest period's rate. */
export function FunnelsDefinitionFields({
    alertForm,
    stepLabels,
    funnelPreview,
    isTrendsFunnel,
    onSetAlertFormValue,
}: {
    alertForm: AlertFormType
    stepLabels: string[]
    funnelPreview: FunnelAlertPreview | null
    isTrendsFunnel: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}): JSX.Element {
    const config = isFunnelsAlertConfig(alertForm.config) ? alertForm.config : null
    if (isTrendsFunnel) {
        // A trends funnel charts the overall conversion rate over time, so there's no per-step choice.
        // The in-progress-period toggle lives in Advanced options, mirroring the trends-alert equivalent.
        return (
            <div className="flex flex-wrap gap-3 items-center">
                <div>Alert on the overall conversion rate</div>
                <FunnelAlertPreviewBanner preview={funnelPreview} />
            </div>
        )
    }
    return (
        <div className="flex flex-wrap gap-3 items-center">
            <div>Alert on</div>
            <LemonSelect
                fullWidth
                className="flex-auto"
                data-attr="alertForm-funnel-conversion"
                placeholder="Select a conversion"
                // Wide funnels generate ~2 options per step; cap the menu so it scrolls instead of overflowing.
                menu={{ className: '!max-h-[400px]' }}
                value={config ? funnelConfigToOptionKey(config, stepLabels.length) : undefined}
                onChange={(key) =>
                    // Each key fully determines the config, so build a fresh one rather than spreading
                    // the previous config (whose type/metric/funnel_step would all be overwritten anyway).
                    onSetAlertFormValue('config', { type: 'FunnelsAlertConfig', ...funnelConfigForOptionKey(key) })
                }
                options={funnelConversionOptions(stepLabels)}
            />
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
            {hasMultipleColumns && (
                <div className="flex gap-3 items-center">
                    <Tooltip title="Names the evaluated row in notifications and the check history.">
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
