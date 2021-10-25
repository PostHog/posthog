import { PersonType } from '~/types'
import React from 'react'
import { IconPerson } from 'lib/components/icons'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import clsx from 'clsx'
import { urls } from 'scenes/urls'

export interface PersonHeaderProps {
    person?: Partial<PersonType> | null
    withIcon?: boolean
}

export const asDisplay = (person: Partial<PersonType> | null | undefined): string => {
    let display, displayId
    const propertyIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : 'with no ids'
    const customIdentifier =
        typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    if (!person?.distinct_ids?.length) {
        displayId = null
    } else {
        const baseId = person.distinct_ids[0].replace(/\W/g, '')
        displayId = baseId.substr(baseId.length - 5).toUpperCase()
    }

    if (person?.is_identified) {
        display = customIdentifier ? customIdentifier : `Identified user ${displayId}`
    } else {
        display = `Unidentified ${customIdentifier || `user ${displayId}`}`
    }

    return display
}

export const asLink = (person: Partial<PersonType> | null | undefined): string | undefined =>
    person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : undefined

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    return (
        <Link to={asLink(props.person)} data-attr="goto-person-email">
            <div
                className={clsx('person-header', {
                    identified: props.person?.is_identified,
                    anonymous: !props.person?.is_identified,
                })}
            >
                {props.withIcon && <IconPerson style={{ marginRight: 8 }} />}
                {props.person?.is_identified ? (
                    <span className="ph-no-capture text-ellipsis">{asDisplay(props.person)}</span>
                ) : (
                    asDisplay(props.person)
                )}
            </div>
        </Link>
    )
}
