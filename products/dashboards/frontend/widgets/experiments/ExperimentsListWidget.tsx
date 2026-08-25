import { clsx } from 'clsx'
import posthog from 'posthog-js'

import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { urls } from 'scenes/urls'

import { type ExperimentConclusion, type ExperimentStatus } from '~/types'

import {
    WIDGET_LIST_COUNT_EXPERIMENTS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseExperimentsListWidgetConfig } from './experimentsWidgetConfigValidation'

const HedgehogExperiment = pngHoggie(experimentPng)

export type ExperimentsListWidgetRow = {
    id: number
    name: string
    status: string
    conclusion: ExperimentConclusion | null
    start_date: string | null
    end_date: string | null
    created_at: string | null
    feature_flag_key: string
    created_by: {
        id: number
        first_name: string
        email: string
    } | null
}

export type ExperimentsListWidgetResult = {
    results?: ExperimentsListWidgetRow[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

function ExperimentConclusionLabel({ conclusion }: { conclusion: ExperimentConclusion }): JSX.Element {
    const config = CONCLUSION_DISPLAY_CONFIG[conclusion]
    return (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted">
            <span className={clsx('size-2 shrink-0 rounded-full', config?.color)} />
            {config?.title ?? conclusion}
        </span>
    )
}

function ExperimentsListWidgetRowItem({ experiment }: { experiment: ExperimentsListWidgetRow }): JSX.Element {
    const creatorName = experiment.created_by?.first_name || experiment.created_by?.email

    return (
        <div className="flex items-center justify-between gap-2 border-b px-2 py-2">
            <div className="flex min-w-0 flex-col">
                <Link
                    to={urls.experiment(experiment.id)}
                    target="_blank"
                    className="truncate font-semibold text-primary"
                    title={experiment.name}
                >
                    {experiment.name}
                </Link>
                <div className="flex min-w-0 items-center gap-1 text-xs text-muted">
                    {experiment.created_at ? (
                        <span className="inline-flex items-center gap-1 whitespace-nowrap">
                            Created <TZLabel time={experiment.created_at} />
                        </span>
                    ) : null}
                    {creatorName ? <span className="truncate">by {creatorName}</span> : null}
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                {experiment.conclusion ? <ExperimentConclusionLabel conclusion={experiment.conclusion} /> : null}
                <StatusTag status={experiment.status as ExperimentStatus} />
            </div>
        </div>
    )
}

function ExperimentsListLoadingSkeleton(): JSX.Element {
    return (
        <div className="flex w-full flex-col" aria-busy aria-label="Loading experiments">
            {Array.from({ length: 5 }, (_, index) => (
                <div key={index} className="flex items-center justify-between gap-2 border-b px-2 py-2" aria-hidden>
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                        <LemonSkeleton className="h-4 w-[55%] max-w-xs" />
                        <LemonSkeleton className="h-3 w-[35%] max-w-40" />
                    </div>
                    <LemonSkeleton className="h-5 w-16 rounded" />
                </div>
            ))}
        </div>
    )
}

export function ExperimentsListWidget({ tileId, config, result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ExperimentsListWidgetResult | null | undefined
    const experiments = payload?.results ?? []
    const parsedConfig = parseExperimentsListWidgetConfig(config)
    const hasActiveFilters = (parsedConfig.status ?? 'all') !== 'all' || parsedConfig.createdBy != null

    if (loading) {
        return (
            <WidgetCardContent>
                <ExperimentsListLoadingSkeleton />
            </WidgetCardContent>
        )
    }

    if (experiments.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="experiments-list-widget-empty-state"
                    >
                        <HedgehogExperiment className="size-20 shrink-0" />
                        {hasActiveFilters ? (
                            <>
                                <p className="m-0 text-base font-semibold text-primary">No experiments found</p>
                                <p className="m-0 text-sm text-muted">
                                    No experiments matched the status and creator filters.
                                </p>
                            </>
                        ) : (
                            <>
                                <p className="m-0 text-base font-semibold text-primary">No experiments yet</p>
                                <p className="m-0 text-sm text-muted">
                                    Run A/B tests to measure the impact of changes on your product.
                                </p>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    to={urls.experiment('new')}
                                    targetBlank
                                    onClick={() =>
                                        posthog.capture('dashboard widget create experiment clicked', {
                                            widget_type: 'experiments_list',
                                            tile_id: tileId,
                                        })
                                    }
                                >
                                    New experiment
                                </LemonButton>
                            </>
                        )}
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {experiments.map((experiment) => (
                        <ExperimentsListWidgetRowItem key={experiment.id} experiment={experiment} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={experiments.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_EXPERIMENTS}
                    hasMore={payload?.hasMore}
                    dataAttr="experiments-list-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
