import { PersonType } from '~/types'
import React from 'react'
import { IconPerson } from 'lib/components/icons'
import './PersonHeader.scss'

export function PersonHeader({ person }: { person: Partial<PersonType> }): JSX.Element {
    const customIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : null
    const distinctId = person?.distinct_ids ? person.distinct_ids[0] : null
    return (
        <>
            {person?.is_identified ? (
                <div className="person-header identified">
                    <span>
                        <IconPerson />
                    </span>
                    {customIdentifier ? (
                        <span className="ph-no-capture text-ellipsis">{customIdentifier}</span>
                    ) : (
                        <i>No email or name set</i>
                    )}
                </div>
            ) : (
                <div className="person-header anonymous">
                    <IconPerson /> Anonymous{' '}
                    {customIdentifier || <>user {distinctId && distinctId.substr(distinctId.length - 5)}</>}
                </div>
            )}
        </>
    )
}
