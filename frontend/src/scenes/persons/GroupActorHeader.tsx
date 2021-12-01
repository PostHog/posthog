import { GroupActorType } from '~/types'
import React from 'react'
import './PersonHeader.scss'

export interface GroupActorHeaderProps {
    actor: GroupActorType
}

export function GroupActorHeader(props: GroupActorHeaderProps): JSX.Element {
    return (
        <div className="person-header identified">
            <span className="ph-no-capture">{props.actor.id}</span>
        </div>
    )
}
