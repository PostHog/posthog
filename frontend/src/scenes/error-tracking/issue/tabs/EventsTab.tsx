import { useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { Query } from '~/queries/Query/Query'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

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

const CustomExceptionColumn: QueryContextColumnComponent = ({ record, value: person }) => {
    // const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    // const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    // const { assignIssue } = useActions(errorTrackingDataNodeLogic)
    // const record = props.record as ErrorTrackingIssue

    console.log(record, value)

    const personProps = {
        withIcon: true,
        noPopover: false,
        person,
    }

    return (
        <LemonTableLink
            onClick={() => {
                debugger
            }}
            title={<PersonDisplay {...personProps} />}
        />
    )
}
