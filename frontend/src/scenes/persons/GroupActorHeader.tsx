import { GroupActorType } from '~/types'
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
                <span className="ph-no-capture">{groupDisplayId(actor.group_key, actor.properties)}</span>
            </div>
        </Link>
    )
}

// Analogue to frontend/src/scenes/persons/PersonHeader.tsx#asDisplay
export function groupDisplayId(groupKey: string, properties: Record<string, any>): string {
    if (properties.name) {
        return String(properties.name)
    }
    return groupKey
}
