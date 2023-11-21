import './ProjectHomepage.scss'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { urls } from 'scenes/urls'
import { PersonType } from '~/types'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { projectHomepageLogic } from './projectHomepageLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'
import { asDisplay } from 'scenes/persons/person-utils'

function PersonRow({ person }: { person: PersonType }): JSX.Element {
    const { reportPersonOpenedFromNewlySeenPersonsList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            to={urls.personByDistinctId(person.distinct_ids[0])}
            title={asDisplay(person)}
            subtitle={`First seen ${dayjs(person.created_at).fromNow()}`}
            prefix={<ProfilePicture name={asDisplay(person)} />}
            onClick={() => {
                reportPersonOpenedFromNewlySeenPersonsList()
            }}
        />
    )
}

export function NewlySeenPersons(): JSX.Element {
    const { persons, personsLoading } = useValues(projectHomepageLogic)

    return (
        <CompactList
            title="Newly seen people"
            viewAllURL={urls.persons()}
            loading={personsLoading}
            emptyMessage={{
                title: 'There are no newly seen people',
                description: 'Learn more about identifying people and ingesting data in the documentation.',
                buttonText: 'Documentation',
                buttonTo: 'https://posthog.com/docs/product-analytics/identify',
            }}
            items={persons.slice(0, 5)}
            renderRow={(person: PersonType, index) => <PersonRow key={index} person={person} />}
        />
    )
}
