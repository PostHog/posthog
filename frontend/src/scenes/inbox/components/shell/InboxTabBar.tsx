import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import {
    INBOX_FLAT_LIST_TAB_KEYS,
    INBOX_STAFF_ONLY_TAB_KEYS,
    INBOX_TAB_KEYS,
    INBOX_TAB_LABEL,
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
    const { count } = useValues(logic)
    return <span className="text-xs text-muted tabular-nums">{count ?? 0}</span>
}

/**
 * Tab bar: Pull requests / Reports (everyone) + Not actionable / Runs (staff-only, with a
 * "Staff" tag). Each report tab shows its own server-computed count. The Configuration tab
 * is only shown when `showConfigTab` is set – i.e. when the scene is too narrow for the
 * setup rail; on wide viewports the rail replaces it.
 */
export function InboxTabBar({ showConfigTab }: { showConfigTab?: boolean }): JSX.Element {
    const { activeTab, isStaff, runsCount } = useValues(inboxSceneLogic)

    const visibleTabKeys = INBOX_TAB_KEYS.filter(
        (key) => (key !== 'config' || showConfigTab) && (!isStaffOnlyTabKey(key) || isStaff)
    )

    return (
        <LemonTabs
            activeKey={activeTab}
            // Hide LemonTabs' own bottom border + margin so the single full-width border lives on the
            // scene header row; the active-tab slider then sits directly on that one border.
            barClassName="before:hidden mb-0"
            onChange={(key) => router.actions.push(urls.inbox(key))}
            tabs={visibleTabKeys.map((key) => ({
                key,
                label: (
                    <span className="flex items-center gap-1.5">
                        <span>{INBOX_TAB_LABEL[key]}</span>
                        {isFlatListTabKey(key) && <FlatTabCount tabKey={key} />}
                        {key === 'runs' && <span className="text-xs text-muted tabular-nums">{runsCount}</span>}
                        {isStaffOnlyTabKey(key) && (
                            <LemonTag type="completion" size="small">
                                Staff
                            </LemonTag>
                        )}
                    </span>
                ),
                content: <></>,
            }))}
        />
    )
}
