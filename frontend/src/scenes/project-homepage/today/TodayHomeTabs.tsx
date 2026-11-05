import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { IconDay, IconPalette, IconSparkles } from '@posthog/icons'
import { Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { TodayHomePage } from './TodayHomePage'
import { TodayHomeTab, todayHomeTabsLogic } from './todayHomeTabsLogic'

const NewSessionStart = lazyWithRetry(() =>
    import('products/tasks/frontend/spaces/NewSessionStart').then((m) => ({ default: m.NewSessionStart }))
)
const TodayHomeCanvas = lazyWithRetry(() => import('./TodayHomeCanvas').then((m) => ({ default: m.TodayHomeCanvas })))

// pinned: the `today-home-tab-*` data-attr values. Autocapture dashboards and Playwright select them.
const HOME_TABS: { value: TodayHomeTab; label: string; Icon: typeof IconDay }[] = [
    { value: 'today', label: 'Today', Icon: IconDay },
    { value: 'ask', label: 'Ask', Icon: IconSparkles },
    { value: 'canvas', label: 'Canvas', Icon: IconPalette },
]

function TodayHomeAskSkeleton(): JSX.Element {
    return (
        <div className="mx-auto flex w-full max-w-150 flex-col gap-3 pt-16" aria-busy>
            <Skeleton className="mx-auto h-6 w-1/2" />
            <Skeleton className="h-32 w-full" />
        </div>
    )
}

/** The Today home page split into Today (the briefing), Ask (a new chat) and Canvas (the person's own canvas). */
export function TodayHomeTabs(): JSX.Element {
    const { tab } = useValues(todayHomeTabsLogic)
    const { pickTab } = useActions(todayHomeTabsLogic)

    return (
        <Tabs
            value={tab}
            onValueChange={(value: TodayHomeTab) => pickTab(value)}
            className="flex min-h-full flex-1 flex-col gap-0"
            data-quill
        >
            <div className="flex shrink-0 justify-center px-4 pt-6">
                <TabsList aria-label="Home views" className="h-auto rounded-full p-1 [--radius-sm:9999px]">
                    {HOME_TABS.map(({ value, label, Icon }) => (
                        <TabsTrigger
                            key={value}
                            value={value}
                            className="h-8 gap-2 !rounded-full px-4 text-sm"
                            data-attr={`today-home-tab-${value}`}
                        >
                            <Icon className="size-4" />
                            <span>{label}</span>
                        </TabsTrigger>
                    ))}
                </TabsList>
            </div>
            <TabsContent value="today">
                <TodayHomePage />
            </TabsContent>
            <TabsContent value="ask" className="flex flex-1 flex-col px-4 pt-10">
                <Suspense fallback={<TodayHomeAskSkeleton />}>
                    <NewSessionStart heading="What do you want to ask?" surface="home_ask" />
                </Suspense>
            </TabsContent>
            <TabsContent value="canvas" className="flex min-h-0 flex-1 flex-col pt-4">
                <Suspense fallback={<Skeleton className="m-4 flex-1" />}>
                    <TodayHomeCanvas />
                </Suspense>
            </TabsContent>
        </Tabs>
    )
}
