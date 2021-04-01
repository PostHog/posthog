import { PersonType } from '~/types'
import React, { useMemo } from 'react'
import { IconPerson } from 'lib/components/icons'
import './PersonHeader.scss'

export function PersonHeader({ person }: { person: Partial<PersonType> }): JSX.Element {
    const customIdentifier = person?.properties
        ? person.properties.email || person.properties.name || person.properties.username
        : null

    const displayId = useMemo(() => {
        if (!person?.distinct_ids?.length) {
            return null
        }
        const baseId = person.distinct_ids[0]
        return baseId.substr(baseId.length - 5).toUpperCase()
    }, [person])

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
                    <IconPerson /> Unidentified {customIdentifier || <>user {displayId}</>}
                </div>
            )}
        </>
    )
}
