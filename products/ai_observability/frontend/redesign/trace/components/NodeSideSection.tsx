import { NodeSideContent } from '../types'
import { IOSection } from './IOSection'
import { MessageSection } from './MessageSection'

export interface NodeSideSectionProps {
    title: string
    side: NodeSideContent
    emptyText: string
    openFrom: number
    highlightQuery?: string | null
}

export function NodeSideSection({
    title,
    side,
    emptyText,
    openFrom,
    highlightQuery = null,
}: NodeSideSectionProps): JSX.Element {
    return side.kind === 'messages' ? (
        <MessageSection
            title={title}
            messages={side.messages}
            emptyText={emptyText}
            openFrom={openFrom}
            highlightQuery={highlightQuery}
        />
    ) : (
        <IOSection title={title} value={side.value} highlightQuery={highlightQuery} />
    )
}
