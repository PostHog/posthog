import { useValues } from 'kea'
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
            'recording_button(properties.$session_id)': {
                title: 'Recording',
                width: '134px',
            },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
    }

    return <Query query={eventsQuery} context={context} />
}
