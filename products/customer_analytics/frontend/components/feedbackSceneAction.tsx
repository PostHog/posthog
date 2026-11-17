import { IconMessage } from '@posthog/icons'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'

import { QuillFeedbackButton } from './QuillFeedbackButton'

/**
 * The "Feedback" scene action, pinned as the title's feedback button. The feedback survey opens on a click of the
 * element with `buttonId`, so the menu row clicks that button and the pin must keep rendering it.
 */
export function feedbackSceneAction(
    dataAttrKey: string,
    buttonId: string,
    {
        group = 'file',
        section = 'feedback',
        order = 1,
    }: { group?: SceneActionGroup; section?: string; order?: number } = {}
): SceneAction {
    return {
        group,
        section,
        id: `${dataAttrKey}-menubar-feedback`,
        label: 'Feedback',
        icon: <IconMessage />,
        tooltip: 'Have any questions or feedback?',
        onSelect: () => document.getElementById(buttonId)?.click(),
        pinned: { order, variant: 'secondary', render: () => <QuillFeedbackButton id={buttonId} /> },
    }
}
