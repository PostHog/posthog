import { LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { SlackWorkspacePicker } from './SlackDestinationPicker'
import { isSlackThreadUrl } from './utils'

export type SlackThreadImportPanelProps = {
    integrationId: number | null
    threadUrl: string
    onIntegrationChange: (integrationId: number | null) => void
    onThreadUrlChange: (url: string) => void
    className?: string
}

/** Workspace picker plus the Slack message link to import a thread from. */
export function SlackThreadImportPanel({
    integrationId,
    threadUrl,
    onIntegrationChange,
    onThreadUrlChange,
    className,
}: SlackThreadImportPanelProps): JSX.Element {
    // Only complain once there's something to complain about — not while the field is still empty.
    const showInvalidHint = !!threadUrl.trim() && !isSlackThreadUrl(threadUrl)

    return (
        <SlackWorkspacePicker
            integrationId={integrationId}
            onIntegrationChange={onIntegrationChange}
            className={className}
        >
            <div className="flex flex-col gap-1">
                <LemonLabel>Slack message link</LemonLabel>
                <LemonInput
                    value={threadUrl}
                    onChange={onThreadUrlChange}
                    placeholder="https://acme.slack.com/archives/C0123ABCD/p1700000000000100"
                    data-attr="discussions-slack-thread-url"
                />
                {showInvalidHint ? (
                    <span className="text-danger text-xs">
                        That doesn't look like a Slack message link. In Slack, use "Copy link" on a message.
                    </span>
                ) : (
                    <span className="text-secondary text-xs">
                        PostHog imports the whole thread and keeps syncing replies both ways. Attachments stay in Slack
                        and are linked; messages from bots and apps are skipped.
                    </span>
                )}
            </div>
        </SlackWorkspacePicker>
    )
}
