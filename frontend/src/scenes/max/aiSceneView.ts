import type { PhaiViewMode } from './maxGlobalLogic'

export interface AiSceneViewInput {
    /** The task `/ai?task=` selects, if any. */
    taskId?: string
    /** The legacy conversation `/ai?chat=` selects, if any. */
    chatId?: string
    /** The view the person saved, collapsed to legacy when the sandbox flag is off. */
    effectivePhaiView: PhaiViewMode
}

/**
 * Which surface the `/ai` scene renders. A task only exists in the new runner and a conversation only
 * exists in the legacy chat, so a link to either has to open that surface whatever view the person
 * saved: both kinds of link are shared and opened cold. A bare `/ai` follows the saved view.
 */
export function aiSceneView({ taskId, chatId, effectivePhaiView }: AiSceneViewInput): 'runner' | 'chat' {
    if (taskId) {
        return 'runner'
    }
    if (chatId) {
        return 'chat'
    }
    return effectivePhaiView === 'new' ? 'runner' : 'chat'
}
