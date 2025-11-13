import { BindLogic, useValues } from 'kea'
import { PropsWithChildren } from 'react'

import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { ErrorTrackingSetupPrompt } from 'products/error_tracking/frontend/components/SetupPrompt/SetupPrompt'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingQuery } from 'products/error_tracking/frontend/queries'
import { IssuesFilters } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesFilters'
import {
    ListOptions,
    useIssueQueryContext,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesList'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const getLogicKey = (nodeId: string): string => {
    return `NotebookNodeIssues:${nodeId}`
}

const ContextualFilters = ({ children, nodeId }: PropsWithChildren<{ nodeId: string }>): JSX.Element => {
    const logicKey = getLogicKey(nodeId)

    return (
        <BindLogic logic={issueFiltersLogic} props={{ logicKey }}>
            <BindLogic logic={issueQueryOptionsLogic} props={{ logicKey }}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeIssuesAttributes>): JSX.Element | null => {
    const { personId, groupKey, groupTypeIndex } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }

    return (
        <ContextualFilters nodeId={attributes.nodeId}>
            <ErrorTrackingSetupPrompt className="border-none">
                <IssuesQuery personId={personId} groupKey={groupKey} groupTypeIndex={groupTypeIndex} />
            </ErrorTrackingSetupPrompt>
        </ContextualFilters>
    )
}

interface IssuesQueryProps {
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
}

const IssuesQuery = ({ personId, groupKey, groupTypeIndex }: IssuesQueryProps): JSX.Element => {
    const { dateRange, filterTestAccounts, filterGroup, searchQuery } = useValues(issueFiltersLogic)
    const { assignee, orderBy, orderDirection, status } = useValues(issueQueryOptionsLogic)

    const context = useIssueQueryContext()
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
        groupKey,
        groupTypeIndex,
    })
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-NotebookNodeIssues-${personId || groupKey}`,
    }

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
            <Query query={{ ...query, embedded: true }} context={context} />
        </BindLogic>
    )
}

export const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeIssuesAttributes>): JSX.Element => {
    return (
        <ContextualFilters nodeId={attributes.nodeId}>
            <div className="p-2 space-y-2 mb-2">
                <IssuesFilters />
                <ListOptions />
            </div>
        </ContextualFilters>
    )
}

type NotebookNodeIssuesAttributes = {
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
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
        groupKey: {},
        groupTypeIndex: {},
    },
})
