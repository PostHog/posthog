import { useActions, useValues } from 'kea'

import { IconBox, IconPlus, IconStar, IconStarFilled } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { TodayAnalyticsNewFolderDialog } from '~/layout/today/TodayAnalyticsNewFolderDialog'

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

function SpaceCard({ space }: { space: AnalyticsSpace }): JSX.Element {
    const { starredPaths, starring } = useValues(analyticsSpacesLogic)
    const { toggleStar } = useActions(analyticsSpacesLogic)
    const counts = ANALYTICS_TYPES.filter((info) => space.counts[info.type] > 0)
    const starred = starredPaths.has(space.path)
    return (
        <Card className="relative h-full transition-colors hover:bg-fill-button-tertiary-hover">
            <CardHeader className="flex-row items-center gap-3 pr-10">
                <AnalyticsSpaceGlyph name={space.name} size="lg" />
                <div className="min-w-0">
                    <CardTitle className="truncate">
                        {/* The link's pseudo-element covers the card, so the whole card opens the space while the star stays its own control. */}
                        <LinkPrimitive
                            to={urls.analyticsList({ folder: space.path })}
                            className="text-foreground after:absolute after:inset-0 after:content-['']"
                            data-attr="analytics-space-card"
                        >
                            {space.name}
                        </LinkPrimitive>
                    </CardTitle>
                    <CardDescription>
                        {space.total === 0
                            ? 'Nothing shared here yet'
                            : `${space.total} ${space.total === 1 ? 'item' : 'items'}${
                                  space.lastAddedAt ? ` · added ${dayjs(space.lastAddedAt).fromNow()}` : ''
                              }`}
                    </CardDescription>
                </div>
            </CardHeader>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="default"
                            size="icon-sm"
                            className="absolute top-2 right-2 z-10"
                            aria-pressed={starred}
                            aria-label={starred ? 'Remove from sidebar' : 'Pin to sidebar'}
                            loading={starring === space.path}
                            onClick={() => toggleStar(space)}
                            data-attr="analytics-space-star"
                        />
                    }
                >
                    {starred ? <IconStarFilled className="text-warning" /> : <IconStar />}
                </TooltipTrigger>
                <TooltipContent>{starred ? 'Remove from sidebar' : 'Pin to the sidebar'}</TooltipContent>
            </Tooltip>
            {counts.length > 0 && (
                <CardContent className="flex flex-wrap gap-x-4 gap-y-1">
                    {counts.map((info) => (
                        <span key={info.type} className="flex items-center gap-1 text-xs text-muted-foreground">
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
                </CardContent>
            )}
        </Card>
    )
}

function AnalyticsSpacesContent(): JSX.Element {
    const { spaces, spacesLoading, spacesFailed } = useValues(analyticsSpacesLogic)
    const { loadSpaces } = useActions(analyticsSpacesLogic)
    const { setNewFolderDialogOpen } = useActions(todayAnalyticsLogic)

    const newSpaceButton = (
        <Button
            variant="primary"
            size="sm"
            onClick={() => setNewFolderDialogOpen(true)}
            data-attr="analytics-spaces-new"
        >
            <IconPlus />
            New space
        </Button>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Spaces"
                description="Where teams keep the analytics they share. Everything else stays personal."
                resourceType={{ type: 'analytics', forceIcon: <IconBox /> }}
                actions={<div data-quill>{newSpaceButton}</div>}
            />
            <div data-quill className="@container/analytics flex flex-col gap-3">
                {spacesFailed ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>Couldn’t load your spaces</EmptyTitle>
                            <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button variant="outline" loading={spacesLoading} onClick={() => loadSpaces()}>
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : spacesLoading && !spaces.length ? (
                    <div
                        className="grid grid-cols-1 gap-3 @2xl/analytics:grid-cols-2 @5xl/analytics:grid-cols-3"
                        aria-busy
                    >
                        {Array.from({ length: 3 }, (_, index) => (
                            <Skeleton key={index} className="h-28" />
                        ))}
                    </div>
                ) : !spaces.length ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No spaces yet</EmptyTitle>
                            <EmptyDescription>
                                Create one for a team or an area, then share analyses into it from their pages.
                            </EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>{newSpaceButton}</EmptyContent>
                    </Empty>
                ) : (
                    <div className="grid grid-cols-1 gap-3 @2xl/analytics:grid-cols-2 @5xl/analytics:grid-cols-3">
                        {spaces.map((space) => (
                            <SpaceCard key={space.path} space={space} />
                        ))}
                    </div>
                )}
                {spaces.length > 0 && (
                    <Text size="xs" variant="muted">
                        Counts come from each space’s newest rows.
                    </Text>
                )}
            </div>
            <TodayAnalyticsNewFolderDialog />
        </SceneContent>
    )
}
