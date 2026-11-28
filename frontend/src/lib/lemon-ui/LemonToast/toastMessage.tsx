import { getIncidentStatus, STATUS_PAGE_BASE } from 'lib/lemon-ui/LemonToast/incidentStatus'
import { renderDetailWithLinks } from 'lib/utils/renderDetailWithLinks'

import { Link } from '../Link'

/**
 * Backend error details often embed a raw docs URL ("... see our docs: https://posthog.com/docs/..."),
 * which as plain toast text is unclickable. `renderDetailWithLinks` links PostHog-host URLs in place,
 * leaving the prose (and any untrusted URL) untouched, so the copy button still carries the full text.
 */
export function withClickableUrls(message: string | JSX.Element): string | JSX.Element {
    if (typeof message !== 'string' || !message.includes('http')) {
        return message
    }
    return <>{renderDetailWithLinks(message)}</>
}

export function incidentNote(className?: string): JSX.Element | undefined {
    if (getIncidentStatus() === 'operational') {
        return undefined
    }
    return (
        <Link className={className} to={STATUS_PAGE_BASE} target="_blank">
            There is an ongoing incident that may be related.
        </Link>
    )
}
