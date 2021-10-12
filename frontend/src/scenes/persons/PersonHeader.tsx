import { PersonType } from '~/types'
import React, { useMemo } from 'react'
import { IconPerson } from 'lib/components/icons'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'

export interface PersonHeader {
    person?: Partial<PersonType> | null
    withIcon?: boolean
}

export function PersonHeader({ person, withIcon = true }: PersonHeader): JSX.Element {
    const propertyIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : null
    const customIdentifier =
        typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    const displayId = useMemo(() => {
        if (!person?.distinct_ids?.length) {
            return null
        }
        const baseId = person.distinct_ids[0].replace(/\W/g, '')
        return baseId.substr(baseId.length - 5).toUpperCase()
    }, [person])

    return (
        <Link
            to={person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : undefined}
            data-attr="goto-person-email"
        >
            {person?.is_identified ? (
                <div className="person-header identified">
                    {withIcon && <IconPerson style={{ marginRight: 8 }} />}
                    {customIdentifier ? (
                        <span className="ph-no-capture text-ellipsis">{customIdentifier}</span>
                    ) : (
                        <i>No email or name set</i>
                    )}
                </div>
            ) : (
                <div className="person-header anonymous">
                    {withIcon && <IconPerson style={{ marginRight: 8 }} />}Unidentified{' '}
                    {customIdentifier || `user ${displayId}`}
                </div>
            )}
        </Link>
    )
}
