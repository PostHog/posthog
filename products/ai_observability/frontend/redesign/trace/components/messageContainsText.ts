import { MessagePart, ThreadMessage } from '../types'

function partText(part: MessagePart): string {
    switch (part.kind) {
        case 'text':
        case 'thinking':
            return part.text
        case 'toolCall':
            return [part.name, JSON.stringify(part.args ?? null), JSON.stringify(part.result ?? null)].join('\n')
        case 'attachment':
            return part.name ?? ''
    }
}

export function messageContainsText(message: ThreadMessage, query: string): boolean {
    const needle = query.toLowerCase()
    return message.parts.some((part) => partText(part).toLowerCase().includes(needle))
}
