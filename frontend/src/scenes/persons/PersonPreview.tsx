import { LemonButton, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { urls } from 'scenes/urls'

import { NotebookNodeType, PropertyDefinitionType } from '~/types'

import { asDisplay } from './person-utils'
import { personLogic } from './personLogic'

export type PersonPreviewProps = {
    distinctId: string
    onClose?: () => void
}

export function PersonPreview(props: PersonPreviewProps): JSX.Element | null {
    const { person, personLoading } = useValues(personLogic({ id: props.distinctId }))

    if (personLoading) {
        return <Spinner />
    }

    // NOTE: This can happen if the Person was deleted or the events associated with the distinct_id had person processing disabled
    if (!person) {
        return (
            <div className="p-2 max-w-160">
                <h4>No profile associated with this ID</h4>
                <p>
                    Person profiles allow you to see a detailed view of a Person's user properties, track users across
                    devices, and more. To create person profiles, see{' '}
                    <Link to="https://posthog.com/docs/data/persons#capturing-person-profiles">here.</Link>
                </p>
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

            <div className="flex-1 overflow-y-auto border-t">
                <PropertiesTable properties={person.properties} type={PropertyDefinitionType.Person} sortProperties />
            </div>
        </div>
    )
}
