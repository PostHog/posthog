import { useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import type { LemonTableColumn } from 'lib/lemon-ui/LemonTable/types'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { experimentsLogic, getExperimentStatus } from 'scenes/experiments/experimentsLogic'
import { StatusTag } from 'scenes/experiments/ExperimentView/components'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagType } from '~/types'

type ExperimentTabContentProps = {
    featureFlag: FeatureFlagType
    multipleExperimentsBannerMessage: React.ReactNode
}

export const ExperimentTabContent = ({
    featureFlag,
    multipleExperimentsBannerMessage,
}: ExperimentTabContentProps): JSX.Element => {
    const { experiments } = useValues(experimentsLogic)
    const relatedExperiments = experiments.results.filter((exp) =>
        featureFlag.experiment_set?.includes(exp.id as number)
    )

    if (relatedExperiments.length === 0) {
        return (
            <div className="flex flex-col items-center pt-5">
                <div className="w-full max-w-5xl">
                    <LemonBanner type="info" className="mb-6">
                        No experiments are using this feature flag yet. Create one to start testing variants.
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
            <LemonBanner type="info">{multipleExperimentsBannerMessage}</LemonBanner>

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
                    createdAtColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
                ]}
            />
        </div>
    )
}
