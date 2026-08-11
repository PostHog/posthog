import { useValues } from 'kea'

import { NotebookExperimentComponent } from '~/scenes/experiments/notebook'
import {
    EXPERIMENT_NOTEBOOK_WIDGET_VIEWS,
    ExperimentNotebookWidgetAttributes,
} from '~/scenes/experiments/notebook/experimentNotebookWidgetViews'
import { createPostHogWidgetNode } from '~/scenes/notebooks/Nodes/NodeWrapper'
import { type NotebookNodeProps, NotebookNodeType } from '~/scenes/notebooks/types'
import { urls } from '~/scenes/urls'

import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<ExperimentNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    return <NotebookExperimentComponent id={id} expanded={expanded} />
}

export const NotebookNodeExperiment = createPostHogWidgetNode<ExperimentNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Experiment,
    titlePlaceholder: 'Experiment',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.experiment(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: {
        key: 'summary',
        label: 'Summary',
        description: 'Use the expandable experiment summary',
    },
    views: EXPERIMENT_NOTEBOOK_WIDGET_VIEWS,
})
