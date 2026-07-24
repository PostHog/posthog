import { useActions, useValues } from 'kea'

import { IconBuilding, IconFolder, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { captureQuickstartAction } from './captureQuickstartAction'
import { LiveUsersRightNow } from './LiveUsersRightNow'
import { UsageThisPeriod } from './UsageThisPeriod'

/** Workspace chrome: where you are, what it costs, what's happening right now */
export function WorkspaceStrip(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-tertiary">
            <div className="flex flex-wrap items-center gap-x-1.5 min-w-0">
                {currentOrganization?.name ? (
                    <span className="flex items-center gap-1">
                        <IconBuilding />
                        {currentOrganization.name}
                    </span>
                ) : null}
                {currentOrganization?.name && currentTeam?.name ? <span>/</span> : null}
                {currentTeam?.name ? (
                    <span className="flex items-center gap-1">
                        <IconFolder />
                        {currentTeam.name}
                    </span>
                ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-x-3">
                <LemonButton
                    size="xsmall"
                    icon={<IconSearch />}
                    onClick={() => {
                        captureQuickstartAction('open_search_shortcut')
                        toggleCommand('quickstart')
                    }}
                    data-attr="quickstart-search-shortcut"
                >
                    <span>Search</span>
                    <RenderKeybind keybind={[keyBinds.search]} minimal />
                </LemonButton>
                <UsageThisPeriod />
                <LiveUsersRightNow />
            </div>
        </div>
    )
}
