import { MessagePart } from '../types'
import { AttachmentPart } from './AttachmentPart'
import { MessageMarkdown } from './MessageMarkdown'
import { ThinkingPart } from './ThinkingPart'
import { ToolCallPart } from './ToolCallPart'

export interface MessagePartViewProps {
    part: MessagePart
}

export function MessagePartView({ part }: MessagePartViewProps): JSX.Element {
    switch (part.kind) {
        case 'text':
            return <MessageMarkdown text={part.text} />
        case 'thinking':
            return <ThinkingPart text={part.text} />
        case 'toolCall':
            return <ToolCallPart name={part.name} args={part.args} result={part.result} isError={part.isError} />
        case 'attachment':
            return (
                <AttachmentPart mediaType={part.mediaType} name={part.name} mimeType={part.mimeType} url={part.url} />
            )
    }
}
