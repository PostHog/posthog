import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import {
    ERROR_TRACKING_ISSUE_NOTEBOOK_WIDGET_VIEWS,
    ErrorTrackingIssueDetail,
    ErrorTrackingIssueNotebookWidgetAttributes,
} from 'products/error_tracking/frontend/errorTrackingIssueNotebookWidgetViews'

import { NotebookNodeType } from '../types'

export const NotebookNodeErrorTrackingIssue = createPostHogWidgetNode<ErrorTrackingIssueNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.ErrorTrackingIssue,
    titlePlaceholder: 'Error tracking issue',
    editableTitle: false,
    Component: ErrorTrackingIssueDetail,
    heightEstimate: 420,
    minHeight: 240,
    href: (attributes) => urls.errorTrackingIssue(attributes.id),
    resizeable: true,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('ErrorTrackingIssue'),
    views: ERROR_TRACKING_ISSUE_NOTEBOOK_WIDGET_VIEWS,
    serializedText: () => 'Error tracking issue',
})
