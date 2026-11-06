import { IconGlobe } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { AccountTabDefinition } from './accountTabs'

interface AccountTabLabelProps {
    tab: AccountTabDefinition
}

export function AccountTabLabel({ tab }: AccountTabLabelProps): JSX.Element {
    if (tab.view?.visibility !== 'team') {
        return <>{tab.label}</>
    }

    return (
        <span className="flex items-center gap-1">
            <span>{tab.label}</span>
            <span className="sr-only">Shared with team</span>
            <Tooltip title="This view is shared with the team.">
                <IconGlobe className="shrink-0 text-muted" />
            </Tooltip>
        </span>
    )
}
