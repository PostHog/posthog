import { LemonBanner } from '@posthog/lemon-ui'

import { regexMatchingErrorMessage } from 'lib/regex/regexMatching'
import { RegexPreviewState } from 'lib/regex/regexMatchingLogic'

export function UrlRegexPreviewStatus({ preview }: { preview: RegexPreviewState }): JSX.Element | null {
    if (preview.status === 'idle') {
        return null
    }
    if (preview.status === 'pending') {
        return (
            <div className="text-xs text-muted" role="status">
                Checking URL…
            </div>
        )
    }
    if (preview.status === 'error') {
        return <LemonBanner type="warning">{regexMatchingErrorMessage(preview.error)}</LemonBanner>
    }
    if (preview.results.some((result) => 'error' in result)) {
        return (
            <LemonBanner type="warning">
                One or more patterns contain invalid regex. Edit these patterns and try again.
            </LemonBanner>
        )
    }
    return (
        <div className="text-xs" role="status">
            {preview.results.some((result) => 'matches' in result && result.matches) ? (
                <span className="text-success">✓ This URL matches at least one pattern</span>
            ) : (
                <span className="text-danger">✗ This URL doesn't match any patterns</span>
            )}
        </div>
    )
}
