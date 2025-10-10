import { BindLogic, useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingQuery } from 'products/error_tracking/frontend/queries'
import { IssuesFilters } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesFilters'
import {
    ListOptions,
    getQueryContext,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesList'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeIssuesAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { personId } = attributes
    const { dateRange, filterTestAccounts, filterGroup, searchQuery } = useValues(issueFiltersLogic({ key: personId }))
    const { assignee, orderBy, orderDirection, status } = useValues(issueQueryOptionsLogic({ key: personId }))
    const query = errorTrackingQuery({
        orderBy,
        status,
        dateRange,
        assignee,
        filterTestAccounts,
        searchQuery,
        filterGroup,
        columns: ['error', 'volume', 'occurrences', 'sessions', 'users'],
        orderDirection,
        personId,
    })
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-NotebookNodeIssues-${personId}`,
    }
    const context = getQueryContext(insightProps)

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
            <Query query={query} context={context} />
        </BindLogic>
    )
}

export const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeIssuesAttributes>): JSX.Element => {
    const { personId } = attributes
    return (
        <BindLogic logic={issueFiltersLogic} props={{ key: personId }}>
            <BindLogic logic={issueQueryOptionsLogic} props={{ key: personId }}>
                <div className="space-y-2 mb-2">
                    <ListOptions />
                    <IssuesFilters />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

type NotebookNodeIssuesAttributes = {
    personId: string
}

export const NotebookNodeIssues = createPostHogWidgetNode<NotebookNodeIssuesAttributes>({
    nodeType: NotebookNodeType.Issues,
    titlePlaceholder: 'Issues',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
    },
})
