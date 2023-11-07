/**
 * NotebookNode messaging
 *
 * To help communication between nodes, you can register a message handler from any of the defined list.
 * Typing wise it is tricky to scope so all events handlers are typed as possibly undefined.
 */

export type NotebookNodeMessages = {
    'play-replay': {
        sessionRecordingId: string
        time: number
    }
    // Not used yet but as a future idea - you could "ping" a node to have it highlight or something.
    ping: {
        message: string
    }
}

export type NotebookNodeMessagesNames = keyof NotebookNodeMessages

export type NotebookNodeMessagesListener<MessageName extends NotebookNodeMessagesNames> = (
    e: NotebookNodeMessages[MessageName]
) => void

export type NotebookNodeMessagesListeners = {
    [MessageName in NotebookNodeMessagesNames]?: NotebookNodeMessagesListener<MessageName>
}
