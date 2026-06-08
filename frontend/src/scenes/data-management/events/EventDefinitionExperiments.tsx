import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Link } from 'lib/lemon-ui/Link'
import {
    EXPERIMENTS_PER_PAGE,
    type ExperimentApi,
    eventExperimentsLogic,
} from 'scenes/data-management/events/eventExperimentsLogic'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EventDefinition, ExperimentStatus } from '~/types'

function getFeatureFlagId(experiment: ExperimentApi): number | undefined {
    const flag = experiment.feature_flag as { id?: number } | undefined
    return flag?.id
}

export function EventDefinitionExperiments({ definition }: { definition: EventDefinition }): JSX.Element {
    const event = definition.name
    const { page, experiments, experimentsLoading } = useValues(eventExperimentsLogic({ event }))
    const { setPage } = useActions(eventExperimentsLogic({ event }))

    const columns: LemonTableColumns<ExperimentApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name, experiment) {
                return <LemonTableLink to={urls.experiment(experiment.id)} title={name as string} />
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: function renderStatus(_, experiment) {
                return <StatusTag status={experiment.status as ExperimentStatus} />
            },
        },
        {
            title: 'Feature flag',
            key: 'feature_flag',
            render: function renderFeatureFlag(_, experiment) {
                const flagId = getFeatureFlagId(experiment)
                return flagId ? (
                    <Link to={urls.featureFlag(flagId)}>{experiment.feature_flag_key}</Link>
                ) : (
                    <span className="text-secondary">{experiment.feature_flag_key}</span>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
            render: function renderCreatedAt(created_at) {
                const time = created_at as string | null
                return <div className="whitespace-nowrap">{time ? <TZLabel time={time} /> : null}</div>
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
