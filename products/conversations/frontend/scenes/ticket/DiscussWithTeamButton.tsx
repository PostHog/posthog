import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { commentsLogic } from 'scenes/comments/commentsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

/**
 * Opens the discussion side panel with a fresh composer focused and, where Slack is set up, already
 * pointed at it — so "I need the team on this" is one click from typing rather than a hunt through the
 * right-hand rail. Deliberately not a modal and not a composer mode: the discussion lives in the panel,
 * and this is just the door to it.
 */
export function DiscussWithTeamButton({
    ticketId,
    disabledReason,
}: {
    ticketId: string
    disabledReason?: string | JSX.Element
}): JSX.Element {
    const logic = commentsLogic({ scope: ActivityScope.TICKET, item_id: ticketId })
    const { maybeLoadComments, startNewComment, setComposerSendToSlack, setComposerSlackIntegrationId } =
        useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { slackIntegrations } = useValues(integrationsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const handleClick = (): void => {
        maybeLoadComments()
        // Leaves any in-progress reply and arms the composer to focus itself once the panel mounts it.
        // Must come before the Slack toggle: exiting reply mode resets the composer's Slack state.
        startNewComment()

        // Only pre-arm when there's a workspace to send to. Without one the picker renders a
        // "not configured" banner while the send button stays disabled on "Select a Slack workspace" —
        // a composer the user can't send from until they notice the toggle and turn it back off.
        if (featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC] && slackIntegrations?.length) {
            setComposerSendToSlack(true)
            if (slackIntegrations.length === 1) {
                setComposerSlackIntegrationId(slackIntegrations[0].id)
            }
        }

        // No options argument: this starts a new discussion, so nothing should be revealed or selected.
        openSidePanel(SidePanelTab.Discussion)
    }

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconChat />}
            onClick={handleClick}
            disabledReason={disabledReason}
            tooltip="Start a team-only discussion about this ticket. The customer never sees it."
            data-attr="ticket-discuss-with-team"
        >
            Discuss with team
        </LemonButton>
    )
}
