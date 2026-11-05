import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { TodayHomePage } from './TodayHomePage'
import { TodayHomeTab, todayHomeTabsLogic } from './todayHomeTabsLogic'

const NewSessionStart = lazyWithRetry(() =>
    import('products/tasks/frontend/spaces/NewSessionStart').then((m) => ({ default: m.NewSessionStart }))
)
const TodayHomeCanvas = lazyWithRetry(() => import('./TodayHomeCanvas').then((m) => ({ default: m.TodayHomeCanvas })))

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
                <TabsList aria-label="Home views">
                    <TabsTrigger value="today" data-attr="today-home-tab-today">
                        Today
                    </TabsTrigger>
                    <TabsTrigger value="ask" data-attr="today-home-tab-ask">
                        Ask
                    </TabsTrigger>
                    <TabsTrigger value="canvas" data-attr="today-home-tab-canvas">
                        Canvas
                    </TabsTrigger>
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
