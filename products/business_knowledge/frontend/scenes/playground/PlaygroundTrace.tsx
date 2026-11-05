import { IconDocument, IconGithub, IconSearch } from '@posthog/icons'

import { Thread } from 'products/posthog_ai/frontend/api/primitives'

import { type SandboxSearchApi, SandboxToolNameEnumApi } from '../../generated/api.schemas'
import { PlaygroundCitations } from './PlaygroundCitations'
import { citationRequest, describeSearch, summarizeSearches } from './playgroundDisplay'

export interface PlaygroundTraceProps {
    id: string
    running: boolean
    searches: SandboxSearchApi[]
    /** Source refs from the answer, used to tag the chunks it cited. */
    citedRefs: string[]
}

function searchIcon(tool: string): JSX.Element {
    if (tool === SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesSearch) {
        return <IconGithub />
    }
    return tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch ? <IconSearch /> : <IconDocument />
}

export function PlaygroundTrace({ id, running, searches, citedRefs }: PlaygroundTraceProps): JSX.Element {
    const steps = searches.map((search, index) => {
        const label = describeSearch(search)
        const request = citationRequest(search)
        return (
            <Thread.Activity
                key={`${search.tool}-${index}`}
                id={`${id}-search-${index}`}
                title={label.title}
                subtitle={label.subtitle}
                status="completed"
                icon={searchIcon(search.tool)}
                animate={false}
                showCompletionIcon={false}
                details={
                    request ? (
                        <PlaygroundCitations
                            citationKey={`${id}-search-${index}`}
                            request={request}
                            citedRefs={citedRefs}
                        />
                    ) : undefined
                }
            />
        )
    })

    // Open while the answer runs, folded once it finishes.
    return (
        <Thread.Activity
            id={`${id}-trace`}
            title={running ? 'Looking through business knowledge' : 'Looked through business knowledge'}
            subtitle={summarizeSearches(searches)}
            status={running ? 'in_progress' : 'completed'}
            animate={running}
            showCompletionIcon={false}
            details={steps.length > 0 ? <div className="flex min-w-0 flex-col gap-1">{steps}</div> : undefined}
        />
    )
}
