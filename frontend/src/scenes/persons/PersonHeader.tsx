import { PersonActorType, PersonType } from '~/types'
import React from 'react'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { teamLogic } from 'scenes/teamLogic'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'

export interface PersonHeaderProps {
    person?: Partial<Pick<PersonType, 'properties' | 'distinct_ids'>> | null
    withIcon?: boolean
    noLink?: boolean
}

export const asDisplay = (person: Partial<PersonType> | PersonActorType | null | undefined): string => {
    let displayId

    const team = teamLogic.findMounted()?.values?.currentTeam
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES

    const customPropertyKey = personDisplayNameProperties.find((x) => person?.properties?.[x])
    const propertyIdentifier = customPropertyKey ? person?.properties?.[customPropertyKey] : undefined

    const customIdentifier =
        typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    if (!person?.distinct_ids?.length) {
        displayId = null
    } else {
        const baseId = person.distinct_ids[0].replace(/\W/g, '')
        displayId = baseId.slice(-5).toUpperCase()
    }

    return customIdentifier ? customIdentifier : `User ${displayId}`
}

export const asLink = (person: Partial<PersonType> | null | undefined): string | undefined =>
    person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : undefined

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const href = asLink(props.person)

    const content = (
        <div className="flex-center">
            {props.withIcon && (
                <ProfilePicture
                    name={
                        props.person?.properties?.email ||
                        props.person?.properties?.name ||
                        props.person?.properties?.username ||
                        (href ? 'U' : '?')
                    }
                    size="md"
                />
            )}
            <span className="ph-no-capture text-ellipsis">{asDisplay(props.person)}</span>
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
