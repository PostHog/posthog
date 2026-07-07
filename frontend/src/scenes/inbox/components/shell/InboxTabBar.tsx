import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSkeleton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import {
    INBOX_FLAT_LIST_TAB_KEYS,
    INBOX_STAFF_ONLY_TAB_KEYS,
    INBOX_TAB_KEYS,
    INBOX_TAB_LABEL,
    INBOX_TAB_TAG,
    InboxFlatListTabKey,
    InboxTabKey,
} from '../../types'

function isFlatListTabKey(tab: InboxTabKey): tab is InboxFlatListTabKey {
    return (INBOX_FLAT_LIST_TAB_KEYS as readonly string[]).includes(tab)
}

function isStaffOnlyTabKey(tab: InboxTabKey): boolean {
    return (INBOX_STAFF_ONLY_TAB_KEYS as string[]).includes(tab)
}

/**
 * Count chip for a flat report tab. Mounts that tab's `reportListLogic` so its `count`
 * (a cheap `limit=1` request) is available for the badge before the tab is ever opened.
 * The active tab shares the same keyed instance, so no double-fetch.
 */
function FlatTabCount({ tabKey }: { tabKey: InboxFlatListTabKey }): JSX.Element {
    const logic = reportListLogic({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
    useMountedLogic(logic)
    const { count, countLoading } = useValues(logic)
    // Skeleton only while the request is genuinely in flight; on failure `count` stays null,
    // so fall back to the number (0) rather than a permanent skeleton.
    if (count === null && countLoading) {
        return <LemonSkeleton className="h-3 w-3 rounded" />
    }
    return <span className="text-xs text-muted tabular-nums">{count ?? 0}</span>
}

/** Synthetic key for the onboarding "Welcome" tab – presentational only, never routed to. */
const WELCOME_TAB_KEY = 'welcome'

type InboxTabBarKey = InboxTabKey | typeof WELCOME_TAB_KEY

/**
 * Tab bar: Pull requests / Reports / Runs (everyone) + Not actionable (staff-only, with a
 * "Staff" tag). Each flat report tab shows its own server-computed count. The Configuration tab is only
 * shown when `showConfigTab` is set – i.e. when the scene is too narrow for the setup rail; on wide
 * viewports the rail replaces it.
 *
 * In `onboarding` mode (self-driving not set up, empty inbox) a locked "Welcome" tab is shown and
 * selected, while the real tabs stay visible but disabled – the user can see what's coming, but the
 * inbox only opens up once self-driving is set up. Code review is the exception: it works without
 * self-driving, so its tab stays clickable.
 */
export function InboxTabBar({
    showConfigTab,
    onboarding,
}: {
    showConfigTab?: boolean
    onboarding?: boolean
}): JSX.Element {
    const { activeTab, isStaff } = useValues(inboxSceneLogic)

    const visibleTabKeys = INBOX_TAB_KEYS.filter(
        (key) => (key !== 'config' || showConfigTab) && (!isStaffOnlyTabKey(key) || isStaff)
    )

    const realTabs = visibleTabKeys.map((key) => ({
        key,
        label: (
            <span className="flex items-center gap-1.5">
                <span>{INBOX_TAB_LABEL[key]}</span>
                {isFlatListTabKey(key) && <FlatTabCount tabKey={key} />}
                {INBOX_TAB_TAG[key] && (
                    <LemonTag type={INBOX_TAB_TAG[key] === 'Alpha' ? 'warning' : 'completion'} size="small">
                        {INBOX_TAB_TAG[key]}
                    </LemonTag>
                )}
            </span>
        ),
        // Code review doesn't need self-driving, so it stays clickable during the takeover.
        disabledReason: onboarding && key !== 'code-review' ? 'Set up self-driving to open your inbox' : undefined,
        content: <></>,
    }))

    const tabs = onboarding
        ? [{ key: WELCOME_TAB_KEY as InboxTabBarKey, label: <span>Welcome</span>, content: <></> }, ...realTabs]
        : realTabs

    return (
        <LemonTabs<InboxTabBarKey>
            activeKey={onboarding ? WELCOME_TAB_KEY : activeTab}
            // min-w-0 lets the tab bar shrink inside the header flex row so its own overflow-x scroll
            // engages on narrow/mobile widths – otherwise it grows to fit every tab and the last ones
            // (e.g. Configuration) overflow off-screen with no way to reach them.
            className="min-w-0"
            // Hide LemonTabs' own bottom border + margin so the single full-width border lives on the
            // scene header row; the active-tab slider then sits directly on that one border.
            barClassName="before:hidden mb-0"
            onChange={(key) => {
                if (key !== WELCOME_TAB_KEY) {
                    router.actions.push(urls.inbox(key))
                }
            }}
            tabs={tabs}
        />
    )
}
