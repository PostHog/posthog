import { NotebookNodeProps, PostHogWidgetViews } from 'scenes/notebooks/types'

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

export const EXPERIMENT_NOTEBOOK_WIDGET_VIEWS = {
    'compact-summary': {
        label: 'Compact summary',
        description: 'Show the experiment status and result significance',
        Component: ExperimentCompactSummary,
    },
    results: {
        label: 'Results',
        description: 'Show experiment exposures and primary metric results',
        Component: ExperimentResults,
    },
} satisfies PostHogWidgetViews<ExperimentNotebookWidgetAttributes>
