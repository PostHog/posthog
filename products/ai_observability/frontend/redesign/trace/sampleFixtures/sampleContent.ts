import { LoadedNodeContent, ThreadMessage } from '../types'

export function messagesContent(input: ThreadMessage[], output: ThreadMessage[]): LoadedNodeContent {
    return {
        kind: 'loaded',
        input: { kind: 'messages', messages: input },
        output: { kind: 'messages', messages: output },
    }
}

export function jsonContent(input: unknown, output: unknown): LoadedNodeContent {
    return { kind: 'loaded', input: { kind: 'json', value: input }, output: { kind: 'json', value: output } }
}
