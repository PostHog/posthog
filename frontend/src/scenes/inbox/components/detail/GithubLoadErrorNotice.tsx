import { Link } from '@posthog/lemon-ui'

import { GithubLoadError } from '../../logics/inboxReportDetailLogic'

/**
 * Inline stand-in for a report section whose GitHub fetch failed. A merged-and-deleted branch is the
 * normal end of a shipped report, so `gone` reads as a plain explanation rather than a failure, and
 * either way the reader gets a way through to the pull request itself.
 */
export function GithubLoadErrorNotice({
    error,
    prUrl,
}: {
    error: GithubLoadError
    prUrl?: string | null
}): JSX.Element {
    return (
        <p className={`m-0 py-2 text-sm ${error.gone ? 'text-tertiary' : 'text-danger'}`}>
            {error.message}
            {prUrl && (
                <>
                    {' '}
                    <Link to={prUrl} target="_blank">
                        View the pull request on GitHub
                    </Link>
                </>
            )}
        </p>
    )
}
