import type { TraceNodeContentApi } from '../../../generated/api.schemas'
import { NodeSideContent, ThreadMessage } from '../types'

export function messagesSides(
    input: ThreadMessage[],
    output: ThreadMessage[]
): { input: NodeSideContent; output: NodeSideContent } {
    return { input: { kind: 'messages', messages: input }, output: { kind: 'messages', messages: output } }
}

export function messagesContent(input: ThreadMessage[], output: ThreadMessage[]): TraceNodeContentApi {
    return messagesSides(input, output)
}

export function jsonContent(input: unknown, output: unknown): TraceNodeContentApi {
    return { input: { kind: 'json', value: input }, output: { kind: 'json', value: output } }
}
