import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { IconExperiment, IconFlag } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useEffect } from 'react'
import { EXPERIMENT_INSIGHT_ID } from 'scenes/experiments/constants'
import { ResultsTag, StatusTag } from 'scenes/experiments/Experiment'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { ExperimentPreview } from 'scenes/experiments/ExperimentPreview'
import { ExperimentResult } from 'scenes/experiments/ExperimentResult'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import { NotebookNodeType } from '~/types'

import { NotebookNodeProps } from '../Notebook/utils'
import { buildFlagContent } from './NotebookNodeFlag'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeExperimentAttributes>): JSX.Element => {
    const { id } = attributes
    const { experiment, experimentLoading, experimentMissing, isExperimentRunning } = useValues(
        experimentLogic({ experimentId: id })
    )
    const { loadExperiment } = useActions(experimentLogic({ experimentId: id }))
    const { expanded } = useValues(notebookNodeLogic)
    const { insertAfter, setActions } = useActions(notebookNodeLogic)

    // experiment progress details
    const logic = insightLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID })
    const { insightProps } = useValues(logic)

    const { conversionMetrics, results } = useValues(funnelDataLogic(insightProps))
    const { results: trendResults } = useValues(trendsDataLogic(insightProps))

    const conversionRate = conversionMetrics.totalRate * 100
    const trendCount = trendResults[0]?.count
    const entrants = results?.[0]?.count

    useEffect(() => {
        setActions([
            {
                text: 'View feature flag',
                icon: <IconFlag />,
                onClick: () => insertAfter(buildFlagContent(experiment.feature_flag?.id || 'new')),
            },
        ])

        loadExperiment()
    }, [id])

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return (
        <div>
            <BindLogic logic={experimentLogic} props={{ experimentId: id }}>
                <div className="flex items-center gap-2 p-3">
                    <IconExperiment className="text-lg" />
                    {experimentLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{experiment.name}</span>
                            <StatusTag experiment={experiment} />
                            <ResultsTag />
                        </>
                    )}
                </div>

                {expanded ? (
                    <>
                        {experiment.description && (
                            <>
                                <LemonDivider className="my-0" />
                                <span className="p-2">{experiment.description}</span>
                            </>
                        )}
                        {!experiment.start_date && (
                            <>
                                <LemonDivider className="my-0" />
                                <div className="p-2">
                                    {/* TODO: Preview is currently shared between all experiments, so if there are 2 experiments in a notebook,
                                they will both show the same preview. This is because there is a single experiment insight ID only, i.e. `EXPERIMENT_INSIGHT_ID` */}
                                    <ExperimentPreview
                                        experimentId={id}
                                        trendCount={trendCount}
                                        trendExposure={experiment?.parameters.recommended_running_time}
                                        funnelSampleSize={experiment?.parameters.recommended_sample_size}
                                        funnelEntrants={entrants}
                                        funnelConversionRate={conversionRate}
                                    />
                                </div>
                            </>
                        )}
                        {isExperimentRunning && (
                            <>
                                {/* show results when the experiment is running */}
                                <LemonDivider className="my-0" />
                                <div className="p-2">
                                    <ExperimentResult />
                                </div>
                            </>
                        )}
                    </>
                ) : null}
            </BindLogic>
        </div>
    )
}

type NotebookNodeExperimentAttributes = {
    id: number
}

export const NotebookNodeExperiment = createPostHogWidgetNode<NotebookNodeExperimentAttributes>({
    nodeType: NotebookNodeType.Experiment,
    titlePlaceholder: 'Experiment',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.experiment(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.experiment('') + '(.+)',
        getAttributes: async (match) => {
            return { id: match[1] as unknown as number }
        },
    },
})
