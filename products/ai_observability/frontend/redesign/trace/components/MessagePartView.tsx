import { MessagePart } from '../types'
import { AttachmentPart } from './AttachmentPart'
import { ThinkingPart } from './ThinkingPart'
import { ToolCallPart } from './ToolCallPart'

export interface MessagePartViewProps {
    part: MessagePart
}

export function MessagePartView({ part }: MessagePartViewProps): JSX.Element {
    switch (part.kind) {
        case 'text':
            return <p className="m-0 whitespace-pre-wrap break-words">{part.text}</p>
        case 'thinking':
            return <ThinkingPart text={part.text} />
        case 'toolCall':
            return <ToolCallPart name={part.name} args={part.args} result={part.result} isError={part.isError} />
        case 'attachment':
            return <AttachmentPart label={part.label} url={part.url} />
    }
}
