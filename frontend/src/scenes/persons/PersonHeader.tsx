import { PersonType } from '~/types'
import React from 'react'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { personHeaderLogic } from 'scenes/persons/personHeaderLogic'
import clsx from 'clsx'
import { ProfilePicture } from 'lib/components/ProfilePicture'

export interface PersonHeaderProps {
    person?: Partial<PersonType> | null
    noIcon?: boolean
}

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const logic = personHeaderLogic(props)
    const { noIcon, personDisplay, personLink, isIdentified, parsedIdentifier } = useValues(logic)

    return (
        <Link to={personLink.length ? personLink : undefined} data-attr="goto-person-email">
            <div className={clsx('person-header', { identified: isIdentified, anonymous: !isIdentified })}>
                {!noIcon && (
                    <ProfilePicture email={props.person?.properties?.email} name={parsedIdentifier.value} size="md" />
                )}
                {isIdentified ? <span className="ph-no-capture text-ellipsis">{personDisplay}</span> : personDisplay}
            </div>
        </Link>
    )
}
