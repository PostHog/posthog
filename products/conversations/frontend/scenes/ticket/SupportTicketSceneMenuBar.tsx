import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { useTodayPeoplePinAction } from '~/layout/today/useTodayPeoplePinAction'

import { supportTicketSceneLogic } from './supportTicketSceneLogic'

const RESOURCE_TYPE = 'ticket'

export function SupportTicketSceneMenuBar({ ticketId }: { ticketId: string }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SupportTicketSceneMenuBarInner ticketId={ticketId} />
}

function SupportTicketSceneMenuBarInner({ ticketId }: { ticketId: string }): JSX.Element {
    const peoplePinActions = useTodayPeoplePinAction()
    const logic = supportTicketSceneLogic({ id: ticketId || 'new' })
    const { ticket, ticketDeleting, deleteDisabledReason } = useValues(logic)
    const { deleteTicket } = useActions(logic)

    const actions: SceneAction[] = [
        ...peoplePinActions,
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-delete`,
            label: 'Delete ticket',
            icon: <IconTrash />,
            destructive: true,
            disabledReason:
                deleteDisabledReason ??
                (!ticket ? 'Ticket is loading' : ticketDeleting ? 'Deleting ticket' : undefined),
            onSelect: () => deleteTicket(),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
