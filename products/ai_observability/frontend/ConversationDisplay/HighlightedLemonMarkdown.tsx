import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { HighlightedContentWrapper } from './HighlightedContentWrapper'

interface HighlightedLemonMarkdownProps {
    children: string
    className?: string
    searchQuery?: string
}

export function HighlightedLemonMarkdown({
    children,
    className,
    searchQuery,
}: HighlightedLemonMarkdownProps): JSX.Element {
    return (
        <HighlightedContentWrapper searchQuery={searchQuery}>
            <LemonMarkdown className={className}>{children}</LemonMarkdown>
        </HighlightedContentWrapper>
    )
}
