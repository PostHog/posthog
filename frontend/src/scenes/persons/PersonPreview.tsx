import { useValues } from 'kea'
import { personLogic } from './personLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { asDisplay } from './PersonHeader'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertyDefinitionType } from '~/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

export type PersonPreviewProps = {
    distinctId: string | undefined
}

export function PersonPreview(props: PersonPreviewProps): JSX.Element {
    if (!props.distinctId) {
        return <></>
    }

    const { person, personLoading } = useValues(personLogic({ id: props.distinctId }))

    if (personLoading) {
        return (
            <>
                <Spinner />
            </>
        )
    }

    if (!person) {
        return <>Not found</>
    }

    const display = asDisplay(person)
    const url = urls.person(person?.distinct_ids[0])

    return (
        <div className="flex flex-col overflow-hidden max-h-80 max-w-160 gap-2">
            <div className="flex items-center justify-between">
                <Link to={url} className="flex gap-2 items-center">
                    <ProfilePicture name={display} size="xl" /> <span className="font-semibold text-lg">{display}</span>
                </Link>
                <LemonButton icon={<IconOpenInNew />} to={urls.person(person?.distinct_ids[0])} />
            </div>

            <div className="flex-1 overflow-y-auto border-t">
                <PropertiesTable properties={person.properties} type={PropertyDefinitionType.Person} sortProperties />
            </div>
        </div>
    )
}
