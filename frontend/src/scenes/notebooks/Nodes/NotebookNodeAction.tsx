import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import {
    ACTION_NOTEBOOK_WIDGET_VIEWS,
    ActionDetail,
    ActionNotebookWidgetAttributes,
} from 'products/actions/frontend/actionNotebookWidgetViews'

import { NotebookNodeType } from '../types'

export const NotebookNodeAction = createPostHogWidgetNode<ActionNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Action,
    titlePlaceholder: 'Action',
    editableTitle: false,
    Component: ActionDetail,
    heightEstimate: 320,
    minHeight: 160,
    href: (attributes) => urls.action(attributes.id),
    resizeable: true,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Action'),
    views: ACTION_NOTEBOOK_WIDGET_VIEWS,
    serializedText: () => 'Action',
})
