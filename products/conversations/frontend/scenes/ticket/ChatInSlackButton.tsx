import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconSlack } from 'lib/lemon-ui/icons'
import { commentsLogic } from 'scenes/comments/commentsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

/**
 * Opens the discussion side panel with a fresh composer focused and already pointed at Slack, so
 * taking a ticket to the team is one click from typing rather than a hunt through the right-hand rail.
 *
 * Renders nothing until a Slack workspace is connected. The button promises Slack, and without a
 * workspace it could not keep that promise: the channel picker would show a "not configured" banner
 * while the send button stayed disabled on "Select a Slack workspace". Teams without Slack still reach
 * the discussion through the side panel's own tab.
 */
export function ChatInSlackButton({
    ticketId,
    disabledReason,
}: {
    ticketId: string
    disabledReason?: string | JSX.Element
}): JSX.Element | null {
    const logic = commentsLogic({ scope: ActivityScope.TICKET, item_id: ticketId })
    const { maybeLoadComments, startNewComment, setComposerSendToSlack, setComposerSlackIntegrationId } =
        useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { slackIntegrations } = useValues(integrationsLogic)

    if (!slackIntegrations?.length) {
        return null
    }

    const handleClick = (): void => {
        maybeLoadComments()
        // Leaves any in-progress reply and arms the composer to focus itself once the panel mounts it.
        // Must come before the Slack toggle: exiting reply mode resets the composer's Slack state.
        startNewComment()

        setComposerSendToSlack(true)
        // One workspace is the common case, and picking it here saves a step. With several, the user
        // has to choose, so leave it unset rather than guess.
        if (slackIntegrations.length === 1) {
            setComposerSlackIntegrationId(slackIntegrations[0].id)
        }

        // No options argument: this starts a new discussion, so nothing should be revealed or selected.
        openSidePanel(SidePanelTab.Discussion)
    }

    return (
        <LemonButton
            size="small"
            icon={<IconSlack />}
            onClick={handleClick}
            disabledReason={disabledReason}
            tooltip="Discuss this ticket in Slack"
            data-attr="ticket-chat-in-slack"
        />
    )
}
