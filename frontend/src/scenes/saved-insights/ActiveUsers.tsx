import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay, asLink } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { PersonType } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { activeUsersLogic } from './activeUsersLogic'

function PersonRow({ person }: { person: PersonType }): JSX.Element {
    const { reportPersonOpenedFromNewlySeenPersonsList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            to={person.uuid ? urls.personByUUID(person.uuid) : asLink(person) || urls.persons()}
            title={asDisplay(person)}
            subtitle={`First seen ${dayjs(person.created_at).fromNow()}`}
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
            title="Most active users"
            viewAllURL={urls.persons()}
            loading={personsLoading}
            emptyMessage={{
                title: 'No active people',
                description: 'People who have been active in your product will appear here.',
                buttonText: 'View all people',
                buttonTo: urls.persons(),
            }}
            items={persons.slice(0, 5)}
            renderRow={(person: PersonType, index) => <PersonRow key={index} person={person} />}
            contentHeightBehavior="fit-content"
        />
    )
}
