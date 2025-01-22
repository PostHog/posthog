import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    PerformanceCardDescriptions,
    PerformanceCardRow,
} from 'scenes/session-recordings/apm/components/PerformanceCard'
import { PerformanceEventLabel } from 'scenes/session-recordings/player/inspector/components/PerformanceEventLabel'

import { PerformanceEvent } from '~/types'

export type NavigationItemProps = {
    item: PerformanceEvent
    expanded: boolean
    navigationURL: string
}

export function NavigationItem({ item, expanded, navigationURL }: NavigationItemProps): JSX.Element | null {
    return (
        <>
            <div className="flex gap-2 items-start px-2 py-1 text-xs">
                <PerformanceEventLabel label="navigated to " expanded={expanded} name={navigationURL} />
            </div>
            <LemonDivider className="my-0" />
            <PerformanceCardRow item={item} />
            <PerformanceCardDescriptions item={item} expanded={expanded} />
        </>
    )
}
