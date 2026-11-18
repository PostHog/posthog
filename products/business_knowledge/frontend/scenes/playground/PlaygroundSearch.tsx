import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'
import { PlaygroundChunk } from './PlaygroundChunk'

export function PlaygroundSearch(): JSX.Element {
    const { searchQuery, searching, searchResults, searchError } = useValues(businessKnowledgePlaygroundLogic)
    const { setSearchQuery, search } = useActions(businessKnowledgePlaygroundLogic)

    return (
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-180 flex-col gap-3 p-4">
                <div className="flex gap-2">
                    <LemonInput
                        type="search"
                        autoFocus
                        fullWidth
                        className="min-w-0 flex-1"
                        placeholder="Search business knowledge"
                        aria-label="Search business knowledge"
                        value={searchQuery}
                        onChange={setSearchQuery}
                        onPressEnter={() => search()}
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-playground-search-query"
                    />
                    <LemonButton
                        type="primary"
                        icon={<IconSearch />}
                        loading={searching}
                        disabledReason={searchQuery.trim() ? undefined : 'Enter something to search for'}
                        onClick={() => search()}
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-playground-search"
                    >
                        Search
                    </LemonButton>
                </div>
                {searching ? (
                    <LemonSkeleton repeat={3} className="h-24" />
                ) : searchError ? (
                    <LemonBanner type="error">{searchError}</LemonBanner>
                ) : searchResults === null ? (
                    <div className="py-8 text-center text-secondary">
                        Search returns the matching chunks from your business knowledge, without writing an answer.
                    </div>
                ) : searchResults.length === 0 ? (
                    <div className="py-8 text-center text-secondary">
                        No chunks match this search. Try other words, or check that your sources finished processing.
                    </div>
                ) : (
                    searchResults.map((result, index) => (
                        <PlaygroundChunk key={result.chunk_id} rank={index + 1} chunk={result} />
                    ))
                )}
            </div>
        </div>
    )
}
