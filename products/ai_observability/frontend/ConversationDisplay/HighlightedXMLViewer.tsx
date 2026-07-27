import { HighlightedContentWrapper } from './HighlightedContentWrapper'
import { XMLViewer } from './XMLViewer'

interface HighlightedXMLViewerProps {
    children: string
    collapsed?: number
    searchQuery?: string
}

export function HighlightedXMLViewer({ children, collapsed = 3, searchQuery }: HighlightedXMLViewerProps): JSX.Element {
    return (
        <HighlightedContentWrapper searchQuery={searchQuery}>
            <XMLViewer collapsed={collapsed}>{children}</XMLViewer>
        </HighlightedContentWrapper>
    )
}
