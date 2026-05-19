import { useValues } from 'kea'

import { NotebookExperimentComponent } from '~/scenes/experiments/notebook'
import { createPostHogWidgetNode } from '~/scenes/notebooks/Nodes/NodeWrapper'
import { type NotebookNodeProps, NotebookNodeType } from '~/scenes/notebooks/types'
import { urls } from '~/scenes/urls'

import { notebookNodeLogic } from './notebookNodeLogic'
import { INTEGER_REGEX_MATCH_GROUPS, OPTIONAL_PROJECT_NON_CAPTURE_GROUP } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeExperimentAttributes>): JSX.Element => {
    const { id } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    return <NotebookExperimentComponent id={id} expanded={expanded} />
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
        find: OPTIONAL_PROJECT_NON_CAPTURE_GROUP + urls.experiment(INTEGER_REGEX_MATCH_GROUPS),
        getAttributes: async (match) => {
            return { id: parseInt(match[1]) }
        },
    },
})
