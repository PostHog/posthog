import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { NotebookExperimentComponent } from './NotebookExperimentComponent'

export type ExperimentNotebookWidgetAttributes = {
    id: number
    view?: string
}

function ExperimentCompactSummary({ attributes }: NotebookNodeProps<ExperimentNotebookWidgetAttributes>): JSX.Element {
    return <NotebookExperimentComponent id={attributes.id} expanded={false} />
}

function ExperimentResults({ attributes }: NotebookNodeProps<ExperimentNotebookWidgetAttributes>): JSX.Element {
    return <NotebookExperimentComponent id={attributes.id} expanded />
}

export const EXPERIMENT_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    ExperimentNotebookWidgetAttributes,
    'Experiment'
>('Experiment', {
    summary: ExperimentCompactSummary,
    results: ExperimentResults,
})
