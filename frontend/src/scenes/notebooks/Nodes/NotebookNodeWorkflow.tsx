import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import {
    WORKFLOW_NOTEBOOK_WIDGET_VIEWS,
    WorkflowDetail,
    WorkflowNotebookWidgetAttributes,
} from 'products/workflows/frontend/workflowNotebookWidgetViews'

import { NotebookNodeType } from '../types'

export const NotebookNodeWorkflow = createPostHogWidgetNode<WorkflowNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Workflow,
    titlePlaceholder: 'Workflow',
    editableTitle: false,
    Component: WorkflowDetail,
    heightEstimate: 420,
    minHeight: 200,
    href: (attributes) => urls.workflow(attributes.id, 'workflow'),
    resizeable: true,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Workflow'),
    views: WORKFLOW_NOTEBOOK_WIDGET_VIEWS,
    serializedText: () => 'Workflow',
})
