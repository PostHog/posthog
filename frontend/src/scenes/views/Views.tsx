import { useActions, useValues } from 'kea'

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

function ViewsContent(): JSX.Element {
    const { views, visibleViews, viewsLoading, loadFailed, search, typeFilter } = useValues(viewsLogic)
    const { setSearch, setTypeFilter, loadViews } = useActions(viewsLogic)
    const failedTypes = views?.failedTypes ?? []

    const newViewButton = (
        <NewViewMenu trigger={<Button variant="primary" size="sm" data-attr="views-new" />}>
            <IconPlus />
            New view
        </NewViewMenu>
    )

    const renderList = (): JSX.Element => {
        if (!views) {
            return loadFailed ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load your views</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={viewsLoading}
                            onClick={() => loadViews()}
                            data-attr="views-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : (
                <ItemGroup combined aria-busy aria-label="Loading your views">
                    {Array.from({ length: 6 }, (_, index) => (
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
                </ItemGroup>
            )
        }
        if (!visibleViews.length) {
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
            <ItemGroup combined>
                {visibleViews.map((view) => (
                    <ViewRow key={`${view.type}-${view.id}`} view={view} />
                ))}
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
                {views && (loadFailed || failedTypes.length > 0) && (
                    <div className="flex flex-wrap items-center gap-2" role="alert">
                        <Text size="sm" variant="destructive">
                            {loadFailed
                                ? 'Couldn’t refresh your views, so this list may be out of date.'
                                : `${failedTypes
                                      .map((type) => VIEW_TYPE_INFO[type].pluralLabel)
                                      .join(' and ')} didn’t load, so this list may be incomplete.`}
                        </Text>
                        <Button
                            variant="outline"
                            size="xs"
                            loading={viewsLoading}
                            onClick={() => loadViews()}
                            data-attr="views-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                {renderList()}
            </div>
        </SceneContent>
    )
}
