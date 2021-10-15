import { PersonType } from '~/types'
import React from 'react'
import { IconPerson } from 'lib/components/icons'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { personHeaderLogic } from 'scenes/persons/personHeaderLogic'
import clsx from 'clsx'

export interface PersonHeaderProps {
    person?: Partial<PersonType> | null
    withIcon?: boolean
}

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const logic = personHeaderLogic(props)
    const { withIcon, personDisplay, personLink, isIdentified } = useValues(logic)

    return (
        <Link to={personLink.length ? personLink : undefined} data-attr="goto-person-email">
            <div className={clsx('person-header', { identified: isIdentified, anonymous: !isIdentified })}>
                {withIcon && <IconPerson style={{ marginRight: 8 }} />}
                {isIdentified ? <span className="ph-no-capture text-ellipsis">{personDisplay}</span> : personDisplay}
            </div>
        </Link>
    )
}
