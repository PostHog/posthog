import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { platformAlertsLogic } from './platformAlertsLogic'

export function PlatformAlertsFacetRailToggle(): JSX.Element {
    const { railCollapsed } = useValues(platformAlertsLogic)
    const { setRailCollapsed } = useActions(platformAlertsLogic)

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={railCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
            onClick={() => setRailCollapsed(!railCollapsed)}
            aria-expanded={!railCollapsed}
            data-attr="platform-alerts-facet-rail-toggle"
        >
            {railCollapsed ? 'Show filters' : 'Hide filters'}
        </LemonButton>
    )
}
