import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { urls } from 'scenes/urls'

export function SessionLogsUnavailableNotice({ sessionId }: { sessionId: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 p-2 max-w-100" data-attr="player-inspector-logs-unavailable-notice">
            <span className="font-semibold">No logs in this session</span>
            <p className="m-0">
                PostHog has no logs linked to this session. Your backend may not send logs to PostHog, or its logs may
                not include the session ID. New logs can take a few minutes to appear.
            </p>
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <span>
                    Session ID:{' '}
                    <CopyToClipboardInline
                        explicitValue={sessionId}
                        description="session ID"
                        iconSize="xsmall"
                        iconPosition="end"
                        className="font-mono"
                    >
                        {sessionId}
                    </CopyToClipboardInline>
                </span>
                <Link
                    to="https://posthog.com/docs/logs/link-session-replay"
                    target="_blank"
                    data-attr="player-inspector-logs-unavailable-docs"
                >
                    Link logs to sessions
                </Link>
                <Link
                    to={urls.settings('environment-logs', 'logs-session-id-attribute-keys')}
                    data-attr="player-inspector-logs-unavailable-settings"
                >
                    Session ID settings
                </Link>
            </div>
        </div>
    )
}
