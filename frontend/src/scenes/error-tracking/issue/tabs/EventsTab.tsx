import { LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import ErrorTrackingFilters from 'scenes/error-tracking/ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

export const EventsTab = (): JSX.Element => {
    const { eventsQuery } = useValues(errorTrackingIssueSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingEventsQuery',
    }

    const context: QueryContext = {
        columns: {
            recording: {
                title: 'Recording',
                width: '140px',
            },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
    }

    return (
        <>
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="my-2" />
            <Query query={eventsQuery} context={context} />
        </>
    )
}
