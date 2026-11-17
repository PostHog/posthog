import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { QuillComposeTicketButton } from '../../components/ComposeTicket/QuillComposeTicketButton'
import { useComposeTicketAction } from '../../components/ComposeTicket/useComposeTicketAction'

const RESOURCE_TYPE = 'support-tickets'

export function SupportTicketsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <SupportTicketsSceneMenuBarInner /> : null
}

function SupportTicketsSceneMenuBarInner(): JSX.Element {
    const newTicketAction = useComposeTicketAction(RESOURCE_TYPE)

    const actions: SceneAction[] = [
        {
            ...newTicketAction,
            pinned: { order: 1, variant: 'primary', render: () => <QuillComposeTicketButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
