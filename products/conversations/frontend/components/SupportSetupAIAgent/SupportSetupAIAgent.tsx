import { combineUrl } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function SupportSetupAIAgent({ supportEnabled }: { supportEnabled: boolean }): JSX.Element {
    return (
        <div className="flex gap-2 border-t border-primary px-4 py-3">
            <IconSparkles className="mt-0.5 size-4 shrink-0 text-secondary" />
            <div className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                    Next: let the AI agent investigate tickets
                    <LemonTag type="highlight" size="small">
                        Beta
                    </LemonTag>
                </span>
                <span className="text-xs text-secondary">
                    The agent drafts a reply to each new ticket as a private note, based on your business knowledge.
                    When a ticket reports something broken, it can check your project's events, errors, session
                    recordings, and logs to find the cause.{' '}
                    {supportEnabled ? (
                        <Link
                            to={combineUrl(urls.supportSettings(), {}, { selectedSetting: 'conversations-ai' }).url}
                            data-attr="support-setup-ai-agent"
                        >
                            Set up the AI agent
                        </Link>
                    ) : (
                        'You can turn it on after you connect a channel.'
                    )}
                </span>
            </div>
        </div>
    )
}
