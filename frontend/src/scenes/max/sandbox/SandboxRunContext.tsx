import { memo } from 'react'

import { IconGitBranch } from '@posthog/icons'

/**
 * Pre-turn header for a sandbox coding run: a one-line "Working on <repo> · <branch> → <base>"
 * summary fed from `runArtifacts`. Plain props, `React.memo`'d. Returns null with no branch, so a
 * pure-analytics conversation (and any run that never reports git context) renders nothing. This
 * complements — does not replace — the `_posthog/progress` provisioning steps.
 */
export const SandboxRunContext = memo(function SandboxRunContext({
    branch,
    baseBranch,
    repo,
}: {
    branch?: string
    baseBranch?: string
    repo?: string
}): JSX.Element | null {
    if (!branch) {
        return null
    }

    return (
        <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-muted" data-attr="max-sandbox-run-context">
            <IconGitBranch className="size-3.5 shrink-0" />
            <span className="min-w-0 truncate">
                Working on{' '}
                {repo ? (
                    <>
                        <span className="font-medium">{repo}</span>
                        {' · '}
                    </>
                ) : null}
                <span className="font-mono">{branch}</span>
                {baseBranch ? (
                    <>
                        {' → '}
                        <span className="font-mono">{baseBranch}</span>
                    </>
                ) : null}
            </span>
        </div>
    )
})
