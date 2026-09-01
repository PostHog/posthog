import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

interface ConversationHistoryProjectScopeProps {
    className?: string
}

// Chats are stored per project, so switching project swaps the whole list. Name the project and
// point at the switcher, so an empty or changed list reads as scoping rather than lost history.
export function ConversationHistoryProjectScope({
    className,
}: ConversationHistoryProjectScopeProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { openProjectSwitcher } = useActions(newAccountMenuLogic)

    if (!currentTeam) {
        return null
    }

    return (
        <div className={cn('flex items-center gap-1 flex-wrap text-secondary min-w-0', className)}>
            <span>Chats in</span>
            <LemonButton
                size="xsmall"
                truncate
                sideIcon={<IconChevronDown />}
                onClick={() => openProjectSwitcher()}
                tooltip="Each project keeps its own chats. Switch project from here."
                aria-label={`Chats in ${currentTeam.name}. Switch project`}
                data-attr="max-conversation-history-project-switch"
            >
                {currentTeam.name}
            </LemonButton>
        </div>
    )
}
