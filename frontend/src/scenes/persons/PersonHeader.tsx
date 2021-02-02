import { PersonType } from '~/types'
import React from 'react'
import { IconPerson } from 'lib/components/icons'

export function PersonHeader({ person }: { person: PersonType }): JSX.Element {
    return (
        <>
            {person.is_identified ? (
                <div className="person-header identified">
                    <IconPerson />{' '}
                    {person.properties.email ? (
                        <span className="ph-no-capture">{person.properties.email}</span>
                    ) : (
                        <i>No email recorded</i>
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
