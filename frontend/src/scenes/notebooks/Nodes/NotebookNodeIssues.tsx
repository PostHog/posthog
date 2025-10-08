import { BindLogic, useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { IssuesFilters } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesFilters'
import {
    ListOptions,
    getQueryContext,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/tabs/issues/IssuesList'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeIssuesAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { personId } = attributes
    const { query } = useValues(errorTrackingSceneLogic({ personId }))
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-NotebookNodeIssues-${personId}`,
    }
    const context = getQueryContext(insightProps)

    if (!expanded) {
        return null
    }

    const key = insightVizDataNodeKey(insightProps)

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key }}>
            <BindLogic logic={issueFiltersLogic} props={{ key }}>
                <BindLogic logic={issueQueryOptionsLogic} props={{ key }}>
                    <div className="space-y-2">
                        <IssuesFilters />
                        <ListOptions isSticky={false} />
                        <Query query={query} context={context} />
                    </div>
                </BindLogic>
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
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
    },
})
