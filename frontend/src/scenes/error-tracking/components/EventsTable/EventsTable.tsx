import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { LemonButton } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { IconTarget } from '@posthog/icons'

export const EventsTable = (): JSX.Element => {
    const { eventsQuery } = useValues(errorTrackingIssueSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingEventsQuery',
    }

    const context: QueryContext = {
        columns: {
            'recording_button(properties.$session_id)': {
                title: 'Recording',
                width: '175px',
                render: (props, record) => (
                    <div className="flex gap-1">
                        <LemonButton 
                            sideIcon={<IconTarget />} 
                            size="xsmall" 
                            type="secondary"
                            disabled={props.recordIndex !== 0 && props.recordIndex !== 2}
                        >
                            <span>Moment</span>
                        </LemonButton>
                        <LemonButton size="xsmall" type="primary" sideIcon={<IconPlayCircle />}>
                            Recording
                        </LemonButton>
                    </div>
                ),
            },
        },
        rowProps: () => {
            return {}
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
    }

    return <Query query={eventsQuery} context={context} />
}
