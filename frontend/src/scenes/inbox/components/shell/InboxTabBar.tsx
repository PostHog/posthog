import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_REPORT_TAB_KEYS, INBOX_TAB_KEYS, INBOX_TAB_LABEL, InboxTabCounts } from '../../types'

interface InboxTabBarProps {
    counts: InboxTabCounts
}

/**
 * Tab bar for the inbox: Pull requests / Reports / Runs, each with a count chip.
 * Mirrors desktop `InboxTabBar`. Navigates between tabs via `urls.inbox(tab)`;
 * the active tab is read from `inboxSceneLogic` (the URL-synced source of truth) —
 * deriving it from the raw pathname is unreliable because of the `/project/<id>` prefix.
 */
export function InboxTabBar({ counts }: InboxTabBarProps): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    return (
        <LemonTabs
            activeKey={activeTab}
            // Hide LemonTabs' own bottom border (`__bar::before`) and bottom margin so the
            // single full-width border lives on the scene header row; the active-tab slider
            // then sits directly on that one border (no double line).
            barClassName="before:hidden mb-0"
            onChange={(key) => router.actions.push(urls.inbox(key))}
            tabs={INBOX_TAB_KEYS.map((key) => ({
                key,
                label: (
                    <span className="flex items-center gap-1.5">
                        <span>{INBOX_TAB_LABEL[key]}</span>
                        {INBOX_REPORT_TAB_KEYS.includes(key) && (
                            <span className="text-xs text-muted tabular-nums">
                                {counts[key as keyof InboxTabCounts]}
                            </span>
                        )}
                    </span>
                ),
                content: <></>,
            }))}
        />
    )
}
