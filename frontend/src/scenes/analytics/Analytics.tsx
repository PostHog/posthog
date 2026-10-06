import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { analyticsHomeLogic } from './analyticsHomeLogic'
import { AnalyticsRow } from './AnalyticsRow'
import { ANALYTICS_TYPES, ANALYTICS_TYPE_ICON_TYPE } from './analyticsUtils'
import { newAnalyticsLogic } from './newAnalyticsLogic'
import { NewAnalyticsMenu } from './NewAnalyticsMenu'

export const scene: SceneExport = {
    component: Analytics,
    logic: analyticsHomeLogic,
}

export function Analytics(): JSX.Element {
    const analyticsEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/analytics` stays a missing page.
    return analyticsEnabled ? <AnalyticsContent /> : <NotFound object="page" />
}

function CreateSection(): JSX.Element {
    const { pickNewAnalyticsType } = useActions(newAnalyticsLogic)

    return (
        <section aria-label="Create something new" className="flex flex-col gap-2">
            <Heading render={<h2 />} size="sm" className="m-0">
                <NewAnalyticsMenu
                    source="home"
                    trigger={
                        <Button
                            variant="link"
                            size="sm"
                            className="h-auto p-0 text-base font-semibold text-foreground"
                            data-attr="analytics-home-create-heading"
                        />
                    }
                >
                    Create something new
                </NewAnalyticsMenu>
            </Heading>
            {/* The product colours on the icons are the only colour here; the rows themselves stay plain. */}
            <ItemGroup className="group/colorful-product-icons colorful-product-icons-true grid grid-cols-1 gap-2 @2xl/analytics:grid-cols-2">
                {ANALYTICS_TYPES.map((info) => (
                    <Item
                        key={info.type}
                        variant="outline"
                        render={<button type="button" />}
                        className="cursor-pointer text-start text-foreground hover:bg-fill-hover"
                        onClick={() => pickNewAnalyticsType(info.type, 'home')}
                        data-attr={`analytics-home-new-${info.type}`}
                    >
                        <ItemMedia variant="icon" aria-hidden>
                            {iconForType(ANALYTICS_TYPE_ICON_TYPE[info.type])}
                        </ItemMedia>
                        <ItemContent className="min-w-0">
                            <ItemTitle>{info.label}</ItemTitle>
                            <ItemDescription>{info.description}</ItemDescription>
                        </ItemContent>
                        <IconPlus className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    </Item>
                ))}
            </ItemGroup>
        </section>
    )
}

function RecentSection(): JSX.Element {
    const { recentAnalytics, recentEntries, recentEntriesLoading, recentsFailed } = useValues(analyticsHomeLogic)
    const { loadRecentEntries } = useActions(analyticsHomeLogic)

    return (
        <section aria-label="Recently viewed" className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <Heading render={<h2 />} size="sm" className="m-0">
                    <Button
                        variant="link"
                        size="sm"
                        nativeButton={false}
                        className="h-auto p-0 text-base font-semibold text-foreground"
                        render={<LinkPrimitive to={urls.analyticsList()} />}
                        data-attr="analytics-home-recent-heading"
                    >
                        Recently viewed
                    </Button>
                </Heading>
                <Button
                    variant="link-muted"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.analyticsList()} />}
                    data-attr="analytics-home-recent-see-all"
                >
                    See all
                </Button>
            </div>
            {recentEntries === null && recentEntriesLoading ? (
                <ItemGroup combined aria-busy>
                    {Array.from({ length: 3 }, (_, index) => (
                        <Skeleton key={index} className="h-12" />
                    ))}
                </ItemGroup>
            ) : recentEntries === null || (recentsFailed && recentAnalytics.length === 0) ? (
                <Empty className="py-6">
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load what you opened recently</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <Button
                        variant="outline"
                        size="sm"
                        loading={recentEntriesLoading}
                        onClick={() => loadRecentEntries()}
                        data-attr="analytics-home-recent-retry"
                    >
                        Try again
                    </Button>
                </Empty>
            ) : recentAnalytics.length === 0 ? (
                <Empty className="py-6">
                    <EmptyHeader>
                        <EmptyTitle>Nothing opened yet</EmptyTitle>
                        <EmptyDescription>Analytics you open show up here, most recent first.</EmptyDescription>
                    </EmptyHeader>
                    <Button
                        variant="outline"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.analyticsList()} />}
                        data-attr="analytics-home-recent-browse"
                    >
                        Browse all analytics
                    </Button>
                </Empty>
            ) : (
                <ItemGroup combined>
                    {recentAnalytics.map((item) => (
                        <AnalyticsRow
                            key={`${item.type}-${item.id}`}
                            analytics={item}
                            backUrl={urls.analytics()}
                            dataAttr="analytics-home-recent-row"
                        />
                    ))}
                </ItemGroup>
            )}
        </section>
    )
}

function AnalyticsContent(): JSX.Element {
    return (
        <SceneContent>
            <div data-quill className="@container/analytics mx-auto flex w-full max-w-5xl flex-col gap-8 py-4">
                <CreateSection />
                <RecentSection />
            </div>
            <AnalyticsCreateModals />
        </SceneContent>
    )
}
