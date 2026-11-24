import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { Tabs, TabsList, TabsTrigger } from '@posthog/quill'

// pinned: the analytics event name in this file feeds dashboards, so renaming it breaks them.

export interface WarehousePageTab {
    /** The `?tab=` value. The first tab is the default and leaves the URL without a `tab` parameter. */
    value: string
    label: string
    'data-attr': string
}

export interface WarehousePageTabsProps {
    tabs: WarehousePageTab[]
    /** Names the page in the `warehouse tab changed` event. */
    page: string
    /** Renders the body of the active tab. Only the active tab renders, so a tab's logics mount on demand. */
    children: (activeTab: string) => React.ReactNode
}

/** Page-level tabs synced to `?tab=`, with the active tab's body below. */
export function WarehousePageTabs({ tabs, page, children }: WarehousePageTabsProps): JSX.Element {
    const { searchParams, location } = useValues(router)
    const activeTab = tabs.find((tab) => tab.value === searchParams.tab)?.value ?? tabs[0].value

    return (
        <>
            <Tabs
                value={activeTab}
                onValueChange={(value) => {
                    const next = String(value)
                    if (next === activeTab) {
                        return
                    }
                    posthog.capture('warehouse tab changed', { page, tab: next })
                    const { tab: _previous, ...rest } = searchParams
                    router.actions.replace(location.pathname, next === tabs[0].value ? rest : { ...rest, tab: next })
                }}
            >
                <TabsList variant="line" aria-label="Sections">
                    {tabs.map((tab) => (
                        <TabsTrigger key={tab.value} value={tab.value} data-attr={tab['data-attr']}>
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            {children(activeTab)}
        </>
    )
}
