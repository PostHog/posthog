import { LoadedNodeContent, NodeSideContent, ThreadMessage } from '../types'

export function messagesSides(
    input: ThreadMessage[],
    output: ThreadMessage[]
): { input: NodeSideContent; output: NodeSideContent } {
    return { input: { kind: 'messages', messages: input }, output: { kind: 'messages', messages: output } }
}

export function messagesContent(input: ThreadMessage[], output: ThreadMessage[]): LoadedNodeContent {
    return { kind: 'loaded', ...messagesSides(input, output) }
}

export function jsonContent(input: unknown, output: unknown): LoadedNodeContent {
    return { kind: 'loaded', input: { kind: 'json', value: input }, output: { kind: 'json', value: output } }
}
