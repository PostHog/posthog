import { useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { StatusTag } from 'scenes/experiments/ExperimentView/components'
import { experimentsLogic, getExperimentStatus } from 'scenes/experiments/experimentsLogic'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagType } from '~/types'

export function ExperimentsTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { experiments } = useValues(experimentsLogic)
    const experimentIds = featureFlag.experiment_set || []
    const relatedExperiments = experiments.results.filter(
        (exp) => typeof exp.id === 'number' && experimentIds.includes(exp.id)
    )

    if (experimentIds.length === 0) {
        return (
            <div className="flex flex-col items-center pt-5">
                <div className="w-full max-w-5xl">
                    <LemonBanner type="info" className="mb-6">
                        Create an experiment using this feature flag to test different variants and measure their impact
                    </LemonBanner>
                    <div className="border rounded p-6 bg-bg-light flex flex-col items-center gap-4">
                        <div className="text-muted text-center">
                            No experiments are using this feature flag yet. Create one to start testing variants.
                        </div>
                        <LemonButton type="primary" to={urls.experiment('new')}>
                            Create experiment
                        </LemonButton>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <LemonBanner type="info">
                Showing experiments associated with this feature flag.{' '}
                <Link to={urls.experiments()}>
                    See all experiments <IconArrowRight />
                </Link>
            </LemonBanner>

            <LemonTable
                dataSource={relatedExperiments}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                rowKey="id"
                nouns={['experiment', 'experiments']}
                data-attr="experiments-table"
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, experiment: Experiment) {
                            return (
                                <LemonTableLink
                                    to={urls.experiment(experiment.id)}
                                    title={stringWithWBR(experiment.name, 17)}
                                />
                            )
                        },
                    },
                    {
                        title: 'Status',
                        dataIndex: 'id',
                        render: function RenderStatus(_, experiment: Experiment) {
                            const status = getExperimentStatus(experiment)
                            return <StatusTag status={status} />
                        },
                    },
                    createdAtColumn() as any,
                ]}
            />
        </div>
    )
}
