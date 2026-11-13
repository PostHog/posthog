import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { githubBranchSearchLogic } from './githubBranchSearchLogic'

export interface UseGitHubDefaultBranchProps {
    integrationId: number
    repo: string
    value: string
    onChange: (value: string | null) => void
}

// Pre-select the repo's default branch once it's known and nothing is chosen yet (matches PostHog Desktop).
// Only a picker still missing a branch pays for the upfront fetch that surfaces it. One that already has
// its branch stays lazy, so a list of them doesn't fire a request per row.
export function useGitHubDefaultBranch({ integrationId, repo, value, onChange }: UseGitHubDefaultBranchProps): void {
    const logic = githubBranchSearchLogic({ integrationId, repo })
    const { defaultBranch } = useValues(logic)
    const { refresh } = useActions(logic)
    const preselectRequestedFor = useRef<string | null>(null)

    useEffect(() => {
        if (value) {
            return
        }
        if (defaultBranch) {
            onChange(defaultBranch)
            return
        }
        const repoKey = `${integrationId}:${repo}`
        if (preselectRequestedFor.current !== repoKey) {
            preselectRequestedFor.current = repoKey
            refresh()
        }
    }, [value, defaultBranch, onChange, refresh, integrationId, repo])
}
