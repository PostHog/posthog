import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheckCircle, IconCorrelationAnalysis, IconInfo, IconPencil, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import { LineChart, type LineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'products/experiments/frontend/constants'
import { reportsMismatch } from 'products/experiments/frontend/health/exposureHealth'

import { experimentLogic } from '../experimentLogic'
import {
    EXPOSURES_HELP,
    ExposuresChart,
    HOLDOUT_HELP,
    NO_EXPOSURES_DESCRIPTION,
    NO_EXPOSURES_TITLE,
    WINNER_HELP,
    useExposuresCard,
} from './exposuresCard'
import { buildExposureSeries } from './exposuresTransforms'
import { QuillExposures } from './QuillExposures'
import { VariantTag } from './VariantTag'

const MISMATCH_LINE_STYLE = {
    warning: { className: 'text-warning font-semibold', icon: <IconWarning className="text-sm" /> },
    info: { className: 'text-secondary', icon: <IconInfo className="text-sm" /> },
}

interface MicroChartProps {
    exposures: ExperimentExposureQueryResponse
}

const CHART_CONFIG: LineChartConfig = {
    hideXAxis: true,
    hideYAxis: true,
    showGrid: false,
    showCrosshair: false,
    curve: 'monotone',
    margins: { top: 1, right: 0, bottom: 1, left: 0 },
    tooltip: { enabled: false },
}

export function MicroChart({ exposures }: MicroChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const timeseries = exposures?.timeseries
    const { labels, series } = useMemo(() => buildExposureSeries(timeseries ?? []), [timeseries])

    if (!timeseries?.length) {
        return null
    }

    return (
        <div className="inline-flex flex-col w-[60px] h-[20px] pointer-events-none border-b border-r border-primary">
            <LineChart series={series} labels={labels} theme={theme} config={CHART_CONFIG} />
        </div>
    )
}

export function Exposures(): JSX.Element {
    const card = useExposuresCard()
    const { exposures } = useValues(experimentLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')

    if (todayRailNav && resultsRedesign) {
        return <QuillExposures {...card} />
    }

    const {
        exposuresLoading,
        exposuresElapsedSeconds,
        exposuresLoadingSlowly,
        totalExposures,
        isEnded,
        exposureCriteriaLabel,
        winnerKey,
        winningKeys,
        winningTooltip,
        multipleTreatmentLabel,
        srmLine,
    } = card

    return (
        <div className="h-full border border-primary rounded bg-[var(--color-bg-table)] px-3 py-2.5 flex flex-col gap-3">
            <div className="flex items-center gap-3 metric-cell">
                <span className="metric-cell-header font-bold inline-flex items-center gap-1">
                    Exposures
                    <Tooltip title={EXPOSURES_HELP}>
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </span>
                {card.holdoutName && (
                    <Tooltip title={HOLDOUT_HELP}>
                        <LemonTag type="option">{card.holdoutName}</LemonTag>
                    </Tooltip>
                )}
                {isEnded ? (
                    <span className="ml-auto text-xs text-secondary">
                        Exposure criteria: <span className="text-primary">{exposureCriteriaLabel}</span>
                    </span>
                ) : (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        className="ml-auto"
                        tooltip={exposureCriteriaLabel}
                        onClick={card.openExposureCriteria}
                    >
                        Exposure criteria
                    </LemonButton>
                )}
            </div>
            <div className="space-y-4">
                {/* Chart Section */}
                {exposuresLoading ? (
                    <div className="relative border rounded h-[200px] flex flex-col gap-3 justify-center items-center">
                        <Spinner className="text-5xl" />
                        {exposuresLoadingSlowly && (
                            <div className="flex flex-col items-center gap-2">
                                <span className="text-secondary text-sm">
                                    Still loading exposures after {exposuresElapsedSeconds}s
                                </span>
                                <LemonButton type="secondary" size="small" onClick={card.retry}>
                                    Retry
                                </LemonButton>
                            </div>
                        )}
                    </div>
                ) : totalExposures === 0 ? (
                    <div className="relative border rounded h-[200px] flex justify-center items-center">
                        <div className="text-center">
                            <IconCorrelationAnalysis className="text-3xl mb-2 text-tertiary" />
                            <div className="text-md font-semibold leading-tight mb-2">{NO_EXPOSURES_TITLE}</div>
                            <p className="text-sm text-center text-balance text-tertiary">{NO_EXPOSURES_DESCRIPTION}</p>
                            {!isEnded && (
                                <div className="flex justify-center mt-4">
                                    <LemonButton
                                        icon={<IconPencil fontSize="12" />}
                                        size="xsmall"
                                        className="flex items-center gap-2"
                                        type="secondary"
                                        onClick={card.editExposureCriteriaFromEmpty}
                                    >
                                        Edit exposure criteria
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <ExposuresChart exposures={exposures} />
                )}

                {(exposures?.timeseries?.length ?? 0) > 0 && (
                    <div>
                        <LemonTable
                            rowClassName={(series) => (series.isExcluded || series.isHoldout ? 'opacity-60' : '')}
                            dataSource={[
                                //This includes EXPERIMENT_VARIANT_MULTIPLE
                                ...(exposures?.timeseries || []),
                                ...card.excludedVariants.map((variant) => ({
                                    variant,
                                    isExcluded: true,
                                })),
                                ...(card.holdoutVariantKey
                                    ? [
                                          {
                                              variant: card.holdoutVariantKey,
                                              isHoldout: true,
                                          },
                                      ]
                                    : []),
                                { variant: '__total__', isTotal: true },
                            ]}
                            columns={[
                                {
                                    title: 'Variant',
                                    key: 'variant',
                                    render: function Variant(_, series) {
                                        if (series.isTotal) {
                                            return <span className="font-semibold">Total</span>
                                        }
                                        const isMultiple = series.variant === EXPERIMENT_VARIANT_MULTIPLE
                                        return (
                                            <div className="flex items-center gap-1.5">
                                                <VariantTag variantKey={series.variant} />
                                                {series.variant === winnerKey && (
                                                    <Tooltip title={WINNER_HELP}>
                                                        <LemonTag type="success" size="small">
                                                            Winner
                                                        </LemonTag>
                                                    </Tooltip>
                                                )}
                                                {winningKeys.has(series.variant) && (
                                                    <Tooltip title={winningTooltip}>
                                                        <LemonTag type="highlight" size="small">
                                                            Winning
                                                        </LemonTag>
                                                    </Tooltip>
                                                )}
                                                {isMultiple && (
                                                    <>
                                                        <span className="text-xs text-secondary">
                                                            ({multipleTreatmentLabel})
                                                        </span>
                                                        {!isEnded && (
                                                            <LemonButton
                                                                icon={<IconPencil fontSize="12" />}
                                                                size="xsmall"
                                                                type="secondary"
                                                                onClick={card.openExposureCriteria}
                                                            />
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        )
                                    },
                                },
                                {
                                    title: 'Exposures',
                                    key: 'exposures',
                                    render: function Exposures(_, { variant, isTotal, isExcluded, isHoldout }) {
                                        if (isTotal) {
                                            return (
                                                <span className="font-semibold">
                                                    {humanFriendlyNumber(totalExposures)}
                                                </span>
                                            )
                                        }
                                        if (isExcluded || isHoldout) {
                                            return <span className="text-secondary">—</span>
                                        }
                                        return humanFriendlyNumber(exposures?.total_exposures[variant])
                                    },
                                },
                                {
                                    title: '%',
                                    key: 'percentage',
                                    render: function Percentage(_, { variant, isTotal, isExcluded, isHoldout }) {
                                        if (isTotal) {
                                            return (
                                                <span className="font-semibold">
                                                    {totalExposures > 0 ? '100.0%' : '-%'}
                                                </span>
                                            )
                                        }
                                        if (isExcluded) {
                                            return <span className="text-secondary italic">Excluded from analysis</span>
                                        }
                                        if (isHoldout) {
                                            return <span className="text-secondary italic">Reserved (holdout)</span>
                                        }
                                        return (
                                            <span className="font-semibold">
                                                {card.variantPercentage(variant) ?? '-%'}
                                            </span>
                                        )
                                    },
                                },
                            ]}
                        />
                        {srmLine && exposures?.sample_ratio_mismatch != null && (
                            <div className="flex items-center gap-1 text-xs mt-2">
                                {reportsMismatch(srmLine) ? (
                                    <>
                                        <Tooltip title={srmLine.tooltip}>
                                            <span
                                                className={`flex items-center gap-1 cursor-pointer ${MISMATCH_LINE_STYLE[srmLine.tone].className}`}
                                            >
                                                {MISMATCH_LINE_STYLE[srmLine.tone].icon}
                                                <span>{srmLine.label}</span>
                                            </span>
                                        </Tooltip>
                                        <span className="text-muted">
                                            (p = {exposures.sample_ratio_mismatch.p_value.toExponential(2)})
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        <Tooltip title={srmLine.tooltip}>
                                            <span className="flex items-center gap-1 text-success cursor-pointer">
                                                <IconCheckCircle className="text-sm" />
                                                <span>{srmLine.label}</span>
                                            </span>
                                        </Tooltip>
                                        <span className="text-muted">
                                            (p = {exposures.sample_ratio_mismatch.p_value.toFixed(3)})
                                        </span>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
