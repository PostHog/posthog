import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { PlaygroundCitationRow } from './PlaygroundCitationRow'
import { playgroundCitationsLogic } from './playgroundCitationsLogic'
import { type PlaygroundCitationRequest, isCitedChunk } from './playgroundDisplay'

export interface PlaygroundCitationsProps {
    citationKey: string
    request: PlaygroundCitationRequest
    /** Source refs from the answer, used to tag the chunks it cited. */
    citedRefs: string[]
}

export function PlaygroundCitations({ citationKey, request, citedRefs }: PlaygroundCitationsProps): JSX.Element {
    const { chunks, chunksError } = useValues(playgroundCitationsLogic({ citationKey, request }))

    if (chunksError) {
        return <LemonBanner type="error">{chunksError}</LemonBanner>
    }
    if (chunks === null) {
        return <LemonSkeleton repeat={3} className="h-5" />
    }
    if (chunks.length === 0) {
        return <div className="text-secondary">No chunks match this search now.</div>
    }
    return (
        <div className="flex min-w-0 flex-col">
            {chunks.map((chunk, index) => (
                <PlaygroundCitationRow
                    key={chunk.chunk_id}
                    chunk={chunk}
                    rank={request.kind === 'search' ? index + 1 : undefined}
                    cited={isCitedChunk(chunk, citedRefs)}
                />
            ))}
        </div>
    )
}
