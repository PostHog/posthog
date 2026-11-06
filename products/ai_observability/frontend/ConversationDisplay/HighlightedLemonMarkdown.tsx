import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { HighlightedContentWrapper } from './HighlightedContentWrapper'

interface HighlightedLemonMarkdownProps {
    children: string
    className?: string
    searchQuery?: string
    disableImages?: boolean
}

export function HighlightedLemonMarkdown({
    children,
    className,
    searchQuery,
    disableImages,
}: HighlightedLemonMarkdownProps): JSX.Element {
    return (
        <HighlightedContentWrapper searchQuery={searchQuery}>
            <LemonMarkdown className={className} disableImages={disableImages}>
                {children}
            </LemonMarkdown>
        </HighlightedContentWrapper>
    )
}
