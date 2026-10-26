import { useActions, useValues } from 'kea'

import { IconBox, IconPin, IconPinFilled, IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { TodayAnalyticsNewFolderDialog } from '~/layout/today/TodayAnalyticsNewFolderDialog'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsSpace, analyticsSpacesLogic } from './analyticsSpacesLogic'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES } from './analyticsUtils'

export const scene: SceneExport = {
    component: AnalyticsSpaces,
    logic: analyticsSpacesLogic,
}

export function AnalyticsSpaces(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    return enabled ? <AnalyticsSpacesContent /> : <NotFound object="page" />
}

/** Each count sits in a cell of one width, so the columns line up down the list whatever the numbers. */
function SpaceCounts({ space, className }: { space: AnalyticsSpace; className?: string }): JSX.Element {
    return (
        <div className={cn('flex flex-wrap gap-x-4 gap-y-1', className)}>
            {ANALYTICS_TYPES.map((info) => (
                <span
                    key={info.type}
                    className="flex items-center gap-1 text-xs whitespace-nowrap text-muted-foreground @3xl/analytics:w-28"
                >
                    <span
                        className="flex [&_svg]:size-4"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: info.color }}
                    >
                        <AnalyticsTypeIcon type={info.type} />
                    </span>
                    <span className="font-semibold text-foreground">{space.counts[info.type]}</span>
                    {space.counts[info.type] === 1 ? info.label.toLowerCase() : info.pluralLabel.toLowerCase()}
                </span>
            ))}
        </div>
    )
}

function SpaceRow({ space }: { space: AnalyticsSpace }): JSX.Element {
    const { pinnedPaths, pinning } = useValues(analyticsSpacesLogic)
    const { togglePin } = useActions(analyticsSpacesLogic)
    const pinned = pinnedPaths.has(space.path)
    return (
        <Item
            variant="outline"
            size="sm"
            className="relative items-center gap-3 transition-colors hover:bg-fill-button-tertiary-hover"
            data-attr="analytics-space-row"
        >
            <ItemMedia>
                <AnalyticsSpaceGlyph name={space.name} size="lg" />
            </ItemMedia>
            <ItemContent className="min-w-0 gap-0.5">
                <ItemTitle className="truncate">
                    {/* The link's pseudo-element covers the row, so the whole row opens the space while the pin stays its own control. */}
                    <LinkPrimitive
                        to={urls.analyticsList({ folder: space.path })}
                        className="text-foreground after:absolute after:inset-0 after:content-['']"
                        data-attr="analytics-space-card"
                    >
                        {space.name}
                    </LinkPrimitive>
                </ItemTitle>
                <ItemDescription>
                    {space.total === 0
                        ? 'Nothing here yet'
                        : `${space.total} ${space.total === 1 ? 'item' : 'items'}${
                              space.lastAddedAt ? ` · added ${dayjs(space.lastAddedAt).fromNow()}` : ''
                          }`}
                </ItemDescription>
                <SpaceCounts space={space} className="mt-1 @3xl/analytics:hidden" />
            </ItemContent>
            <SpaceCounts space={space} className="hidden shrink-0 @3xl/analytics:flex" />
            <ItemActions className="relative z-10 shrink-0 self-center">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="default"
                                size="icon"
                                aria-pressed={pinned}
                                aria-label={pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
                                loading={pinning === space.path}
                                onClick={() => togglePin(space)}
                                data-attr="analytics-space-star"
                            />
                        }
                    >
                        {pinned ? <IconPinFilled className="size-5 text-warning" /> : <IconPin className="size-5" />}
                    </TooltipTrigger>
                    <TooltipContent>{pinned ? 'Unpin from the sidebar' : 'Pin to the sidebar'}</TooltipContent>
                </Tooltip>
            </ItemActions>
        </Item>
    )
}

function AnalyticsSpacesContent(): JSX.Element {
    const { spaces, visibleSpaces, spacesLoading, spacesFailed, search, pagination } = useValues(analyticsSpacesLogic)
    const { refreshSpaces, loadMore, setSearch } = useActions(analyticsSpacesLogic)
    const { setNewFolderDialogOpen } = useActions(todayAnalyticsLogic)

    const newSpaceButton = (
        <Button
            variant="primary"
            size="sm"
            onClick={() => setNewFolderDialogOpen(true)}
            data-attr="analytics-spaces-new"
        >
            <IconPlus />
            New collection
        </Button>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Collections"
                description="Where teams keep the work they share."
                resourceType={{ type: 'analytics', forceIcon: <IconBox /> }}
                actions={<div data-quill>{newSpaceButton}</div>}
            />
            <div data-quill className="@container/analytics flex flex-col gap-3">
                {spacesFailed ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>Couldn’t load your collections</EmptyTitle>
                            <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button variant="outline" loading={spacesLoading} onClick={() => refreshSpaces()}>
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : spacesLoading && !spaces.length && !search ? (
                    <div className="flex flex-col gap-2" aria-busy>
                        {Array.from({ length: 4 }, (_, index) => (
                            <Skeleton key={index} className="h-16" />
                        ))}
                    </div>
                ) : !spaces.length && !search && !pagination.hasMore ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No collections yet</EmptyTitle>
                            <EmptyDescription>
                                Create one for a team or an area, then add work to it from each item's page.
                            </EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>{newSpaceButton}</EmptyContent>
                    </Empty>
                ) : (
                    <>
                        <AnalyticsSearchInput
                            value={search}
                            onChange={setSearch}
                            label="Search collections"
                            placeholder="Search collections"
                            dataAttr="analytics-spaces-search"
                        />
                        {spacesLoading && !visibleSpaces.length && <Spinner aria-label="Loading collections" />}
                        {visibleSpaces.length > 0 && (
                            <ItemGroup className="flex flex-col gap-2 pb-8">
                                {visibleSpaces.map((space) => (
                                    <SpaceRow key={space.path} space={space} />
                                ))}
                            </ItemGroup>
                        )}
                        {!visibleSpaces.length && !pagination.hasMore && !spacesLoading && (
                            <Empty>
                                <EmptyHeader>
                                    <EmptyMedia variant="icon">
                                        <IconSearch />
                                    </EmptyMedia>
                                    <EmptyTitle>No collection matches</EmptyTitle>
                                    <EmptyDescription>Try a different name, or clear the search.</EmptyDescription>
                                </EmptyHeader>
                                <EmptyContent>
                                    <Button
                                        variant="outline"
                                        onClick={() => setSearch('')}
                                        data-attr="analytics-spaces-clear-search"
                                    >
                                        Clear search
                                    </Button>
                                </EmptyContent>
                            </Empty>
                        )}
                        {pagination.hasMore && (
                            <Button
                                variant="outline"
                                loading={spacesLoading}
                                onClick={() => loadMore()}
                                data-attr="analytics-spaces-load-more"
                            >
                                Load more
                            </Button>
                        )}
                    </>
                )}
            </div>
            <AnalyticsCreateModals />
            <TodayAnalyticsNewFolderDialog />
        </SceneContent>
    )
}
