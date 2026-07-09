import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Link } from 'lib/lemon-ui/Link'
import {
    EXPERIMENTS_PER_PAGE,
    type ExperimentBasicApi,
    eventExperimentsLogic,
} from 'scenes/data-management/events/eventExperimentsLogic'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EventDefinition, ExperimentStatus } from '~/types'

export function EventDefinitionExperiments({ definition }: { definition: EventDefinition }): JSX.Element {
    const event = definition.name
    const { page, experiments, experimentsLoading } = useValues(eventExperimentsLogic({ event }))
    const { setPage } = useActions(eventExperimentsLogic({ event }))

    const columns: LemonTableColumns<ExperimentBasicApi> = [
        {
            title: 'Name',
            key: 'name',
            render: function renderName(_, experiment) {
                return <LemonTableLink to={urls.experiment(experiment.id)} title={experiment.name} />
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: function renderStatus(_, experiment) {
                // ExperimentStatusEnumApi shares the ExperimentStatus enum's values; bridge the nominal gap.
                return <StatusTag status={experiment.status as ExperimentStatus} />
            },
        },
        {
            title: 'Feature flag',
            key: 'feature_flag',
            render: function renderFeatureFlag(_, experiment) {
                // feature_flag is typed once the regenerated MinimalFeatureFlag schema lands; read id defensively until then.
                const flagId = (experiment.feature_flag as { id?: number } | null)?.id
                return flagId ? (
                    <Link to={urls.featureFlag(flagId)}>{experiment.feature_flag_key}</Link>
                ) : (
                    <span className="text-secondary">{experiment.feature_flag_key}</span>
                )
            },
        },
        {
            title: 'Created',
            key: 'created_at',
            render: function renderCreatedAt(_, experiment) {
                return (
                    <div className="whitespace-nowrap">
                        {experiment.created_at ? <TZLabel time={experiment.created_at} /> : null}
                    </div>
                )
            },
        },
    ]

    return (
        <SceneSection title="Experiments using event">
            <LemonTable
                id={`event-definition-experiments-table-${definition.id}`}
                loading={experimentsLoading}
                columns={columns}
                data-attr="event-definition-experiments-table"
                dataSource={experiments.results}
                pagination={{
                    controlled: true,
                    currentPage: page,
                    entryCount: experiments.count,
                    pageSize: EXPERIMENTS_PER_PAGE,
                    onForward: experiments.next ? () => setPage(page + 1) : undefined,
                    onBackward: experiments.previous ? () => setPage(page - 1) : undefined,
                }}
                rowKey="id"
                loadingSkeletonRows={EXPERIMENTS_PER_PAGE}
                nouns={['experiment', 'experiments']}
                emptyState="No experiments use this event"
            />
        </SceneSection>
    )
}
