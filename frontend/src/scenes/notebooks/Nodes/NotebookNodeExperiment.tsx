import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { BindLogic, useActions, useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeProps } from '../Notebook/utils'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { buildFlagContent } from './NotebookNodeFlag'
import { useEffect } from 'react'
import { NotFound } from 'lib/components/NotFound'
import { IconFlag, IconFlask } from '@posthog/icons'
import { ResultsQuery, ResultsTag, StatusTag } from 'scenes/experiments/ExperimentView/components'
import { SummaryTable } from 'scenes/experiments/ExperimentView/SummaryTable'
import { Info } from 'scenes/experiments/ExperimentView/Info'
import { INTEGER_REGEX_MATCH_GROUPS } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeExperimentAttributes>): JSX.Element => {
    const { id } = attributes
    const { experiment, experimentLoading, experimentMissing, isExperimentRunning, experimentResults } = useValues(
        experimentLogic({ experimentId: id })
    )
    const { loadExperiment } = useActions(experimentLogic({ experimentId: id }))
    const { expanded } = useValues(notebookNodeLogic)
    const { insertAfter, setActions } = useActions(notebookNodeLogic)

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
                    <IconFlask className="text-lg" />
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
                                    <Info />
                                </div>
                            </>
                        )}
                        {isExperimentRunning && (
                            <>
                                <LemonDivider className="my-0" />
                                <div className="p-2">
                                    <SummaryTable />
                                    <ResultsQuery targetResults={experimentResults} showTable={true} />
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
        find: urls.experiment(INTEGER_REGEX_MATCH_GROUPS),
        getAttributes: async (match) => {
            return { id: parseInt(match[1]) }
        },
    },
})
