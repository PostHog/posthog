import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay, asLink } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { ActivePersonType, activeUsersLogic } from './activeUsersLogic'

function PersonRow({ person }: { person: ActivePersonType }): JSX.Element {
    const { reportPersonOpenedFromNewlySeenPersonsList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            to={person.uuid ? urls.personByUUID(person.uuid) : asLink(person) || urls.persons()}
            title={asDisplay(person)}
            subtitle={
                <div className="flex items-center gap-1">
                    <span className="font-medium">
                        {person.activity_count} {person.activity_count === 1 ? 'event' : 'events'}
                    </span>
                    <span>•</span>
                    <span>First seen {dayjs(person.created_at).fromNow()}</span>
                </div>
            }
            prefix={<ProfilePicture name={asDisplay(person)} />}
            onClick={() => {
                reportPersonOpenedFromNewlySeenPersonsList()
            }}
            dataAttr="active-user-item"
        />
    )
}

export function ActiveUsers(): JSX.Element {
    const { persons, personsLoading } = useValues(activeUsersLogic)

    return (
        <CompactList
            title={
                <div className="flex items-center gap-1">
                    Most active users
                    <Tooltip title="Users with the most events in the last 7 days. For large volumes of data this is calculated on a sample of events.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </div>
            }
            viewAllURL={urls.persons()}
            viewAllDataAttr="insights-home-tab-active-users-view-all"
            loading={personsLoading}
            emptyMessage={{
                title: 'No active people',
                description: 'People who have been active in your product will appear here.',
                buttonText: 'View all people',
                buttonTo: urls.persons(),
            }}
            items={persons.slice(0, 5)}
            renderRow={(person: ActivePersonType, index) => <PersonRow key={index} person={person} />}
            contentHeightBehavior="fit-content"
        />
    )
}
