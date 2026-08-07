import { useValues } from 'kea'

import { NotebookExperimentComponent } from '~/scenes/experiments/notebook'
import { createPostHogWidgetNode } from '~/scenes/notebooks/Nodes/NodeWrapper'
import { type NotebookNodeProps, NotebookNodeType } from '~/scenes/notebooks/types'
import { urls } from '~/scenes/urls'

import { notebookNodeLogic } from './notebookNodeLogic'

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
})
