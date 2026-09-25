import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { ActivePersonType, activeUsersLogic } from './activeUsersLogic'
import { PersonRow } from './PersonRow'

export function ActiveUsers(): JSX.Element {
    const { persons, personsLoading, personsLoadedError } = useValues(activeUsersLogic)
    const { loadPersons } = useActions(activeUsersLogic)

    return (
        <CompactList
            title={
                <div className="flex items-center gap-1">
                    Most active users
                    <Tooltip title="Users with the most events in the last 7 days. For large data volumes, PostHog uses an event sample.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </div>
            }
            viewAllURL={urls.persons()}
            viewAllDataAttr="insights-home-tab-active-users-view-all"
            loading={personsLoading}
            error={personsLoadedError}
            errorMessage={{
                title: "Couldn't load active users",
                description: 'Something went wrong loading this list.',
                buttonText: 'Retry',
                buttonOnClick: loadPersons,
            }}
            emptyMessage={{
                title: 'No active people',
                description: 'People who have been active in your product will appear here.',
                buttonText: 'View all people',
                buttonTo: urls.persons(),
            }}
            items={persons.slice(0, 5)}
            renderRow={(person: ActivePersonType) => <PersonRow key={person.id} person={person} />}
            contentHeightBehavior="fit-content"
        />
    )
}
