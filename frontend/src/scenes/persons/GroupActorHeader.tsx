import { GroupActorType } from '~/types'
import React from 'react'
import { IconPersonFilled } from 'lib/components/icons'
import './PersonHeader.scss'

export interface GroupActorHeaderProps {
    actor?: Partial<GroupActorType> | null
    withIcon?: boolean
}

export function GroupActorHeader(props: GroupActorHeaderProps): JSX.Element {
    return (
        <div className="person-header identified">
            {props.withIcon && <IconPersonFilled style={{ marginRight: 8 }} />}
            <span className="ph-no-capture">{props.actor?.properties?.name || props.actor?.id}</span>
        </div>
    )
}
