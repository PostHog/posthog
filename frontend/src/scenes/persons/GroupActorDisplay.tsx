import './PersonDisplay.scss'

import { IconInfo } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
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
                <Tooltip
                    title={
                        <>
                            Group wasn't identified at the time of the event.{' '}
                            <Link
                                to="https://posthog.com/docs/product-analytics/group-analytics#how-to-create-groups"
                                target="_blank"
                            >
                                Learn&nbsp;more
                            </Link>
                        </>
                    }
                >
                    <IconInfo className="text-secondary" />
                </Tooltip>
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
    if (properties?.name) {
        return String(properties.name)
    }
    return groupKey
}
