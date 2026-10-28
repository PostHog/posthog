import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { supportTicketSceneLogic } from './supportTicketSceneLogic'

export function SupportTicketSceneMenuBar({ ticketId }: { ticketId: string }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SupportTicketSceneMenuBarInner ticketId={ticketId} />
}

function SupportTicketSceneMenuBarInner({ ticketId }: { ticketId: string }): JSX.Element {
    const logic = supportTicketSceneLogic({ id: ticketId || 'new' })
    const { ticket, ticketDeleting, deleteDisabledReason } = useValues(logic)
    const { deleteTicket } = useActions(logic)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="ticket-menubar-file">
                <SceneMenuBarItem
                    variant="destructive"
                    disabled={!ticket || ticketDeleting || !!deleteDisabledReason}
                    tooltip={deleteDisabledReason}
                    onClick={() => deleteTicket()}
                    data-attr="ticket-menubar-delete"
                >
                    <IconTrash />
                    Delete ticket
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
