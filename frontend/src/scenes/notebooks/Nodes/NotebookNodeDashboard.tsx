import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import {
    DASHBOARD_NOTEBOOK_WIDGET_VIEWS,
    DashboardDetail,
    DashboardNotebookWidgetAttributes,
} from 'products/dashboards/frontend/dashboardNotebookWidgetViews'

import { NotebookNodeType } from '../types'

export const NotebookNodeDashboard = createPostHogWidgetNode<DashboardNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Dashboard,
    titlePlaceholder: 'Dashboard',
    editableTitle: false,
    Component: DashboardDetail,
    heightEstimate: 640,
    minHeight: 240,
    href: (attributes) => urls.dashboard(attributes.id),
    resizeable: true,
    expandable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Dashboard'),
    views: DASHBOARD_NOTEBOOK_WIDGET_VIEWS,
    serializedText: () => 'Dashboard',
})
