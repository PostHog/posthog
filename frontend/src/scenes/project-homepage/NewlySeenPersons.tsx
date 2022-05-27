import React from 'react'
import './ProjectHomepage.scss'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { LemonButton } from 'lib/components/LemonButton'
import { urls } from 'scenes/urls'
import { PersonType } from '~/types'

import { ProfilePicture } from 'lib/components/ProfilePicture'
import { projectHomepageLogic } from './projectHomepageLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay } from 'scenes/persons/PersonHeader'

function PersonRow({ person }: { person: PersonType }): JSX.Element {
    const { reportPersonOpenedFromNewlySeenPersonsList } = useActions(eventUsageLogic)

    return (
        <LemonButton
            fullWidth
            className="list-row"
            to={urls.person(person.distinct_ids[0])}
            onClick={() => {
                reportPersonOpenedFromNewlySeenPersonsList()
            }}
        >
            <ProfilePicture name={asDisplay(person)} />

            <div className="row-text-container" style={{ flexDirection: 'column', display: 'flex' }}>
                <p className="row-title link-text">{asDisplay(person)}</p>
                <p>First seen {dayjs(person.created_at).fromNow()}</p>
            </div>
        </LemonButton>
    )
}

export function NewlySeenPersons(): JSX.Element {
    const { persons, personsLoading } = useValues(projectHomepageLogic)

    return (
        <CompactList
            title="Newly seen persons"
            viewAllURL={urls.persons()}
            loading={personsLoading}
            emptyMessage={{
                title: 'There are no newly seen persons',
                description: 'Learn more about identifying persons and ingesting data in the documentation.',
                buttonText: 'Documentation',
                buttonTo: 'https://posthog.com/docs/integrate/identifying-users',
            }}
            items={persons.slice(0, 5)}
            renderRow={(person: PersonType, index) => <PersonRow key={index} person={person} />}
        />
    )
}
