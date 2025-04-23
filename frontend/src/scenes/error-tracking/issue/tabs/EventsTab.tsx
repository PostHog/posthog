import { IconRewindPlay } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyIcons } from 'lib/components/PropertyIcons/PropertyIcons'
import { TZLabel } from 'lib/components/TZLabel'
import { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { Query } from '~/queries/Query/Query'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { EventType, InsightLogicProps } from '~/types'

export const EventsTab = (): JSX.Element => {
    const { eventsQuery } = useValues(errorTrackingIssueSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingEventsQuery',
    }

    const context: QueryContext = {
        columns: {
            person: {
                render: CustomExceptionColumn,
            },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
    }

    return (
        <div>
            <Query query={eventsQuery} context={context} />
        </div>
    )
}

const CustomExceptionColumn: QueryContextColumnComponent = ({ record }) => {
    const { setActiveException } = useActions(errorTrackingIssueSceneLogic)
    const [exception, person] = record as [EventType, { distinct_id: string }]

    const currentUrl = exception.properties.$current_url

    return (
        <LemonTableLink
            className="w-full"
            onClick={() => setActiveException(exception)}
            title={<PersonDisplay noLink noPopover person={person} />}
            description={
                <div className="space-y-0.5">
                    {currentUrl && <div className="truncate">{currentUrl}</div>}
                    <div className="flex space-x-1">
                        <TZLabel time={exception.timestamp} showSeconds />
                        <PropertyIcons properties={exception.properties} iconClassNames="text-secondary" />
                        {mightHaveRecording(exception.properties) && (
                            <Tooltip title="Recording captured">
                                <div className="inline-flex items-center text-secondary">
                                    <IconRewindPlay />
                                </div>
                            </Tooltip>
                        )}
                    </div>
                </div>
            }
        />
    )
}
