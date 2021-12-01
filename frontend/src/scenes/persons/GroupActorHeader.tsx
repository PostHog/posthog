import { GroupActorType } from '~/types'
import React from 'react'
import './PersonHeader.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'

export interface GroupActorHeaderProps {
    actor: GroupActorType
}

export function GroupActorHeader({ actor }: GroupActorHeaderProps): JSX.Element {
    return (
        <Link to={urls.group(actor.group_type_index.toString(), actor.group_key)}>
            <div className="person-header identified">
                <span className="ph-no-capture">{actor.id}</span>
            </div>
        </Link>
    )
}
