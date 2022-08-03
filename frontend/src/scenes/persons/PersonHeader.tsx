import { PersonActorType, PersonType } from '~/types'
import React from 'react'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { teamLogic } from 'scenes/teamLogic'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { midEllipsis } from 'lib/utils'

export interface PersonHeaderProps {
    person?: Pick<PersonType, 'properties' | 'distinct_ids'> | null
    withIcon?: boolean
    noLink?: boolean
}

export function asDisplay(person: PersonType | PersonActorType | null | undefined): string {
    if (!person) {
        return 'Unknown'
    }
    const team = teamLogic.findMounted()?.values?.currentTeam
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES

    const customPropertyKey = personDisplayNameProperties.find((x) => person.properties?.[x])
    const propertyIdentifier = customPropertyKey ? person.properties?.[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    const display: string | undefined = (customIdentifier || person.distinct_ids?.[0])?.trim()

    return display ? midEllipsis(display, 40) : 'Person without ID'
}

export const asLink = (person: Partial<PersonType> | null | undefined): string | undefined =>
    person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : undefined

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const href = asLink(props.person)
    const display = asDisplay(props.person)

    const content = (
        <div className="flex items-center">
            {props.withIcon && <ProfilePicture name={display} size="md" />}
            <span className="ph-no-capture text-ellipsis">{display}</span>
        </div>
    )

    return (
        <div className="person-header">
            {props.noLink || !href ? (
                content
            ) : (
                <Link to={href} data-attr={`goto-person-email-${props.person?.distinct_ids?.[0]}`}>
                    {content}
                </Link>
            )}
        </div>
    )
}
