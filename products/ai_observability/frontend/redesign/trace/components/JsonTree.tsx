import { useMemo } from 'react'

import { JSONViewer } from 'lib/components/JSONViewer'

import type { JSONDisplayContainer } from '../../../components/JSONValueDisplay'
import { searchableText } from './jsonText'
import { ShowMore } from './ShowMore'

const OPEN_DEPTH = 2
// Captured values can nest thousands of levels deep, and React renders nested components recursively.
const SEARCH_OPEN_DEPTH = 64

export interface JsonTreeProps {
    src: JSONDisplayContainer
    highlightQuery?: string | null
}

export function JsonTree({ src, highlightQuery = null }: JsonTreeProps): JSX.Element {
    const showsQuery = useMemo(
        () => !!highlightQuery && searchableText(src).toLowerCase().includes(highlightQuery.toLowerCase()),
        [src, highlightQuery]
    )

    // Strings wrap between words and keep line breaks. The hidden copy icon sits outside the line, so it never wraps.
    return (
        <ShowMore highlightQuery={highlightQuery} nested>
            <div className="min-w-0 [&_.string-value]:whitespace-pre-wrap [&_.string-value]:![word-break:normal] [&_.variable-value]:max-w-[calc(100%-2rem)] [&_.variable-row_.copy-to-clipboard-container]:absolute">
                <JSONViewer
                    key={showsQuery ? 'open' : 'collapsed'}
                    src={src}
                    collapsed={showsQuery ? SEARCH_OPEN_DEPTH : OPEN_DEPTH}
                    escapeStrings={false}
                />
            </div>
        </ShowMore>
    )
}
