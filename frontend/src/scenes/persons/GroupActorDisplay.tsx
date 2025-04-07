import './PersonDisplay.scss'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { GroupActorType } from '~/types'

export interface GroupActorDisplayProps {
    actor: GroupActorType
}

export function GroupActorDisplay({ actor }: GroupActorDisplayProps): JSX.Element {
    if (!actor.group_key) {
        return (
            <div>
                Unidentified group{' '}
                <Link
                    to="https://posthog.com/docs/product-analytics/group-analytics#how-to-create-groups"
                    target="_blank"
                    className="font-normal text-xs"
                >
                    Learn more
                </Link>
            </div>
        )
    }
    return (
        <Link to={urls.group(actor.group_type_index.toString(), actor.group_key)}>
            <div className="identified">
                <span className="ph-no-capture">{groupDisplayId(actor.group_key, actor.properties)}</span>
            </div>
        </Link>
    )
}

// Analogue to frontend/src/scenes/persons/PersonDisplay.tsx#asDisplay
export function groupDisplayId(groupKey: string, properties: Record<string, any>): string {
    if (properties.name) {
        return String(properties.name)
    }
    return groupKey
}
