import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconGridMasonry, IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Item,
    ItemContent,
    ItemGroup,
    ItemMedia,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewViewMenu } from './NewViewMenu'
import { ViewRow } from './ViewRow'
import { viewsLogic } from './viewsLogic'
import { VIEW_TYPES, VIEW_TYPE_INFO, ViewTypeFilter } from './viewsUtils'

const SCROLL_PREFETCH_MARGIN = '1200px 0px'

export const scene: SceneExport = {
    component: Views,
    logic: viewsLogic,
}

const TYPE_FILTERS: { value: ViewTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    ...VIEW_TYPES.map((info) => ({ value: info.type, label: info.pluralLabel })),
]

/** Canvases, notebooks and dashboards in one list. */
export function Views(): JSX.Element {
    const viewsEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/views` stays a missing page.
    return viewsEnabled ? <ViewsContent /> : <NotFound object="page" />
}

function ViewRowSkeletons({ count }: { count: number }): JSX.Element {
    return (
        <>
            {Array.from({ length: count }, (_, index) => (
                <Item key={index} variant="outline" size="sm">
                    <ItemMedia variant="icon">
                        <Skeleton className="size-4" />
                    </ItemMedia>
                    <ItemContent className="gap-1.5">
                        <Skeleton className="h-3.5 w-48 max-w-full" />
                        <Skeleton className="h-3 w-32 max-w-full" />
                    </ItemContent>
                </Item>
            ))}
        </>
    )
}

function ViewsContent(): JSX.Element {
    const { feed, feedStale, search, typeFilter } = useValues(viewsLogic)
    const { setSearch, setTypeFilter, loadViews, loadMoreViews } = useActions(viewsLogic)
    const { ref: endRef, inView: endInView } = useInView({
        root: document.getElementById('main-content'),
        rootMargin: SCROLL_PREFETCH_MARGIN,
    })
    const { items, initialized, loading, hasMore, failedTypes, loadFailed } = feed

    useEffect(() => {
        if (endInView && hasMore) {
            loadMoreViews()
        }
    }, [endInView, hasMore, items.length, loadMoreViews])

    const newViewButton = (
        <NewViewMenu trigger={<Button variant="primary" size="sm" data-attr="views-new" />}>
            <IconPlus />
            New view
        </NewViewMenu>
    )

    const renderList = (): JSX.Element => {
        if (loadFailed) {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load your views</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" loading={loading} onClick={() => loadViews()} data-attr="views-retry">
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (!initialized) {
            return (
                <ItemGroup combined aria-busy aria-label="Loading your views">
                    <ViewRowSkeletons count={6} />
                </ItemGroup>
            )
        }
        if (!items.length) {
            const filterLabel = typeFilter === 'all' ? 'views' : VIEW_TYPE_INFO[typeFilter].pluralLabel.toLowerCase()
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconGridMasonry />
                        </EmptyMedia>
                        <EmptyTitle>{search ? 'Nothing matches that search' : `No ${filterLabel} yet`}</EmptyTitle>
                        <EmptyDescription>
                            {search
                                ? 'Try a different name, or clear the search.'
                                : 'Canvases, notebooks and dashboards you create show up here.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    {!search && <EmptyContent>{newViewButton}</EmptyContent>}
                </Empty>
            )
        }
        return (
            <ItemGroup
                combined
                aria-busy={feedStale || hasMore}
                className={feedStale ? 'opacity-60 transition-opacity' : 'transition-opacity'}
            >
                {items.map((view) => (
                    <ViewRow key={`${view.type}-${view.id}`} view={view} />
                ))}
                {hasMore && <ViewRowSkeletons count={3} />}
            </ItemGroup>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Views"
                description="Canvases, notebooks and dashboards in this project."
                resourceType={{ type: 'views', forceIcon: <IconGridMasonry /> }}
                actions={<div data-quill>{newViewButton}</div>}
            />
            <div data-quill className="@container/views flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <InputGroup className="min-w-48 flex-1">
                        <InputGroupAddon align="inline-start">
                            <InputGroupText>
                                <IconSearch />
                            </InputGroupText>
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            aria-label="Search views"
                            placeholder="Search views"
                            value={search}
                            onChange={(event: React.ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                            data-attr="views-search"
                        />
                    </InputGroup>
                    <ToggleGroup
                        size="sm"
                        aria-label="Filter by type"
                        value={[typeFilter]}
                        onValueChange={(value: string[]) => value[0] && setTypeFilter(value[0] as ViewTypeFilter)}
                    >
                        {TYPE_FILTERS.map((filter) => (
                            <ToggleGroupItem key={filter.value} value={filter.value} data-attr="views-type-filter">
                                {filter.label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </div>
                {initialized && !loadFailed && failedTypes.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2" role="alert">
                        <Text size="sm" variant="destructive">
                            {`${failedTypes
                                .map((type) => VIEW_TYPE_INFO[type].pluralLabel)
                                .join(' and ')} didn’t load, so this list may be incomplete.`}
                        </Text>
                        <Button
                            variant="outline"
                            size="xs"
                            loading={loading}
                            onClick={() => loadViews()}
                            data-attr="views-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                {renderList()}
                <div ref={endRef} aria-hidden />
            </div>
        </SceneContent>
    )
}
