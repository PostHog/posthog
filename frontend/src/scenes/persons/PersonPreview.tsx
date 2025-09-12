import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { urls } from 'scenes/urls'

import { ActivityTab, PropertyDefinitionType, PropertyFilterType, PropertyOperator } from '~/types'

import { asDisplay } from './person-utils'
import { personsLogic } from './personsLogic'

export type PersonPreviewProps = {
    distinctId?: string
    personId?: string
    onClose?: () => void
}

export function PersonPreview(props: PersonPreviewProps): JSX.Element | null {
    const { loadPerson, loadPersonUUID } = useActions(personsLogic({ syncWithUrl: false }))
    const { person, personLoading } = useValues(personsLogic({ syncWithUrl: false }))

    useEffect(() => {
        if (props.distinctId) {
            loadPerson(props.distinctId)
        } else if (props.personId) {
            loadPersonUUID(props.personId)
        }
    }, [loadPerson, loadPersonUUID, props.distinctId, props.personId])

    if (!props.distinctId && !props.personId) {
        return null
    }

    if (personLoading) {
        return <Spinner />
    }

    // NOTE: This can happen if the Person was deleted or the events associated with the distinct_id had person processing disabled
    if (!person) {
        const eventsQuery = getDefaultEventsSceneQuery([
            {
                type: PropertyFilterType.EventMetadata,
                key: 'distinct_id',
                value: props.distinctId,
                operator: PropertyOperator.Exact,
            },
        ])
        const eventsUrl = combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: eventsQuery }).url
        return (
            <div className="p-2 max-w-160">
                <h4>No profile associated with this ID</h4>
                <p>
                    Person profiles allow you to see a detailed view of a Person's user properties, track users across
                    devices, and more. To create person profiles, see{' '}
                    <Link to="https://posthog.com/docs/data/persons#capturing-person-profiles">here.</Link>
                </p>
                <div className="flex justify-center mt-2 w-fit">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={eventsUrl}
                        tooltip={`View events matching distinct_id=${props.distinctId}`}
                    >
                        View events
                    </LemonButton>
                </div>
            </div>
        )
    }

    const display = asDisplay(person)
    const url = urls.personByDistinctId(person?.distinct_ids[0])

    return (
        <div className="flex flex-col overflow-hidden max-h-80 max-w-160 gap-2">
            <div className="flex items-center justify-between min-h-10 px-2">
                <Link to={url} className="flex gap-2 items-center flex-1">
                    <ProfilePicture name={display} /> <span className="font-semibold">{display}</span>
                </Link>

                <NotebookSelectButton
                    resource={{
                        type: NotebookNodeType.Person,
                        attrs: { id: person?.distinct_ids[0] },
                    }}
                    onNotebookOpened={() => props.onClose?.()}
                    size="small"
                />
                <LemonButton size="small" icon={<IconOpenInNew />} to={url} />
            </div>

            <ScrollableShadows direction="vertical">
                <PropertiesTable
                    properties={person.properties}
                    type={PropertyDefinitionType.Person}
                    sortProperties
                    embedded={false}
                />
            </ScrollableShadows>
        </div>
    )
}
