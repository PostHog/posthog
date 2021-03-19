import { PersonType } from '~/types'
import React from 'react'
import { IconPerson } from 'lib/components/icons'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import './PersonHeader.scss'

export function PersonHeader({ person }: { person: Partial<PersonType> }): JSX.Element {
    const customIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : null
    return (
        <>
            {person?.is_identified ? (
                <div className="person-header identified">
                    <span>
                        <IconPerson />
                    </span>
                    {customIdentifier ? (
                        <span className={`text-ellipsis ${rrwebBlockClass}`}>{customIdentifier}</span>
                    ) : (
                        <i>No email or name set</i>
                    )}
                </div>
            ) : (
                <div className="person-header anonymous">
                    <IconPerson /> Anonymous user
                </div>
            )}
        </>
    )
}
