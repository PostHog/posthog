import { PersonType } from '~/types'
import React from 'react'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { ProfilePicture } from 'lib/components/ProfilePicture'

export interface PersonHeaderProps {
    person?: Partial<Pick<PersonType, 'properties' | 'distinct_ids'>> | null
    withIcon?: boolean
    noLink?: boolean
}

export const asDisplay = (person: Partial<PersonType> | null | undefined): string => {
    let displayId
    const propertyIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : 'with no IDs'
    const customIdentifier =
        typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    if (!person?.distinct_ids?.length) {
        displayId = null
    } else {
        const baseId = person.distinct_ids[0].replace(/\W/g, '')
        displayId = baseId.substr(baseId.length - 5).toUpperCase()
    }

    return customIdentifier ? customIdentifier : `User ${displayId}`
}

export const asLink = (person: Partial<PersonType> | null | undefined): string | undefined =>
    person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : undefined

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const content = (
        <div className="flex-center">
            {props.withIcon && (
                <span className="mr-025">
                    <ProfilePicture
                        name={
                            props.person?.properties?.email ||
                            props.person?.properties?.name ||
                            props.person?.properties?.username ||
                            'U'
                        }
                        size="md"
                    />
                </span>
            )}
            <span className="ph-no-capture text-ellipsis">{asDisplay(props.person)}</span>
        </div>
    )

    return (
        <div className="person-header">
            {props.noLink ? (
                content
            ) : (
                <Link to={asLink(props.person)} data-attr={`goto-person-email-${props.person?.distinct_ids?.[0]}`}>
                    {content}
                </Link>
            )}
        </div>
    )
}
