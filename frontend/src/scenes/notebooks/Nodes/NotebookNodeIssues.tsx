import { BindLogic, useActions, useValues } from 'kea'
import { PropsWithChildren } from 'react'

import { IconX } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupLogic } from 'scenes/groups/groupLogic'

import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'
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
import { getLogicKey } from './utils'

const ContextualFilters = ({ children, logicKey }: PropsWithChildren<{ logicKey: string }>): JSX.Element => {
    return (
        <BindLogic logic={issueFiltersLogic} props={{ logicKey }}>
            <BindLogic logic={issueQueryOptionsLogic} props={{ logicKey }}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeIssuesAttributes>): JSX.Element | null => {
    const { personId, groupKey, groupTypeIndex, tabId } = attributes
    const { expanded } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const logicKey = getLogicKey({ tabId, personId, groupKey })
    const { removeNode } = useActions(customerProfileLogic)

    useOnMountEffect(() => {
        setMenuItems([
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.Issues),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

    if (!expanded) {
        return null
    }

    return (
        <ContextualFilters logicKey={logicKey}>
            <ErrorTrackingSetupPrompt className="border-none">
                <IssuesQuery
                    personId={personId}
                    groupKey={groupKey}
                    groupTypeIndex={groupTypeIndex}
                    logicKey={logicKey}
                />
            </ErrorTrackingSetupPrompt>
        </ContextualFilters>
    )
}

interface IssuesQueryProps {
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
    logicKey: string
}

const IssuesQuery = ({ personId, groupKey, groupTypeIndex, logicKey }: IssuesQueryProps): JSX.Element => {
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
        limit: 10,
    })
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-NotebookNodeIssues-${personId || groupKey}`,
    }
    const attachTo = groupTypeIndex !== undefined && groupKey ? groupLogic({ groupTypeIndex, groupKey }) : undefined

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
            <Query uniqueKey={logicKey} attachTo={attachTo} query={{ ...query, embedded: true }} context={context} />
        </BindLogic>
    )
}

export const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeIssuesAttributes>): JSX.Element => {
    const { groupKey, personId, tabId } = attributes
    const logicKey = getLogicKey({ groupKey, personId, tabId })

    return (
        <ContextualFilters logicKey={logicKey}>
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
    tabId: string
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
        tabId: {},
    },
})
