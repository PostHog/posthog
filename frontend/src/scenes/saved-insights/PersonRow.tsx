import { useActions } from 'kea'

import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { asDisplay, asLink } from 'products/persons/frontend/person-utils'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { ActivePersonType } from './activeUsersLogic'

export function PersonRow({ person }: { person: ActivePersonType }): JSX.Element {
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
            onClick={reportPersonOpenedFromNewlySeenPersonsList}
            dataAttr="active-user-item"
        />
    )
}
