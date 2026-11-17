import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLetter } from '@posthog/icons'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { composeTicketLogic } from './composeTicketLogic'

interface ComposeTicketActionOptions {
    distinctId?: string
    email?: string
    group?: SceneActionGroup
    section?: string
}

/** The "New ticket" scene action. With support off it opens support settings, as the title button's popover does. */
export function useComposeTicketAction(
    dataAttrKey: string,
    { distinctId, email, group = 'file', section = 'create' }: ComposeTicketActionOptions = {}
): SceneAction {
    const { currentTeam } = useValues(teamLogic)
    const { openComposeModal } = useActions(composeTicketLogic)
    const conversationsEnabled = !!currentTeam?.conversations_enabled

    return {
        group,
        section,
        id: `${dataAttrKey}-menubar-new-ticket`,
        label: 'New ticket',
        icon: <IconLetter />,
        opensFloatingUi: conversationsEnabled,
        tooltip: conversationsEnabled
            ? undefined
            : 'Support is not enabled for this project. Enable it in settings to start writing to customers.',
        disabledReason:
            getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined,
        onSelect: () =>
            conversationsEnabled
                ? openComposeModal({ distinctId, email })
                : router.actions.push(urls.supportSettings()),
    }
}
