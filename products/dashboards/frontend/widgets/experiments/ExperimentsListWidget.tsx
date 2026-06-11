import { ExperimentsHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { urls } from 'scenes/urls'

import type { ExperimentStatus } from '~/types'

import {
    WIDGET_LIST_COUNT_EXPERIMENTS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WidgetLoadingState,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'

export type ExperimentsListWidgetRow = {
    id: number
    name: string
    status: string
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

function ExperimentsListWidgetRowItem({ experiment }: { experiment: ExperimentsListWidgetRow }): JSX.Element {
    const creatorName = experiment.created_by?.first_name || experiment.created_by?.email

    return (
        <div className="flex items-center justify-between gap-2 border-b px-2 py-2">
            <div className="flex min-w-0 flex-col">
                <Link
                    to={urls.experiment(experiment.id)}
                    className="truncate font-semibold text-primary"
                    title={experiment.name}
                >
                    {experiment.name}
                </Link>
                <span className="truncate text-xs text-muted">
                    {experiment.created_at ? (
                        <>
                            Created <TZLabel time={experiment.created_at} />
                        </>
                    ) : null}
                    {creatorName ? <> by {creatorName}</> : null}
                </span>
            </div>
            <StatusTag status={experiment.status as ExperimentStatus} />
        </div>
    )
}

export function ExperimentsListWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ExperimentsListWidgetResult | null | undefined
    const experiments = payload?.results ?? []

    if (loading) {
        return <WidgetLoadingState rowCount={4} />
    }

    if (experiments.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="experiments-list-widget-empty-state"
                    >
                        <ExperimentsHog className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No experiments found</p>
                        <p className="m-0 text-sm text-muted">No experiments matched the status and creator filters.</p>
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
