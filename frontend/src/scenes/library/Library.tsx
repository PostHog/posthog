import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import {
    Button,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    SkeletonText,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { TodayQuillRoot } from '~/layout/today/TodayQuillRoot'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { LibraryCreateButton } from './LibraryCreateButton'
import { libraryLogic } from './libraryLogic'
import { baseObjectType, libraryObjectHref, libraryObjectName } from './libraryUtils'

export const scene: SceneExport = {
    component: Library,
    logic: libraryLogic,
}

/** Saved objects across the project, filtered by the type in the URL. */
export function Library(): JSX.Element {
    const libraryEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/library` stays a missing page.
    return libraryEnabled ? <LibraryContent /> : <NotFound object="page" />
}

function LibraryContent(): JSX.Element {
    const { objectType, objectTypeByValue, visibleObjects, objectsLoading, loadFailed, search, hasMore } =
        useValues(libraryLogic)
    const { setSearch, loadObjects, loadMoreObjects } = useActions(libraryLogic)
    const selectedType = objectType ? objectTypeByValue[objectType] : undefined
    const title = selectedType?.pluralLabel ?? 'All objects'
    const emptyMessage = hasMore
        ? 'Nothing to show on the pages loaded so far. Select Show more to keep looking.'
        : search
          ? 'Nothing matches that search.'
          : selectedType
            ? `No ${selectedType.pluralLabel.toLowerCase()} yet. Create one to see it here.`
            : 'Insights, dashboards, flags and everything else you save show up here.'

    return (
        <SceneContent>
            <SceneTitleSection
                name={title}
                description={
                    selectedType
                        ? null
                        : 'Everything saved in this project. Pick a type in the sidebar to narrow the list.'
                }
                resourceType={{ type: objectType || 'folder' }}
                actions={
                    selectedType ? (
                        <div data-quill className="contents">
                            <LibraryCreateButton
                                objectType={selectedType.value}
                                label={`New ${selectedType.label.toLowerCase()}`}
                            />
                        </div>
                    ) : undefined
                }
            />
            <TodayQuillRoot className="flex flex-col gap-4">
                <Input
                    type="search"
                    placeholder={`Search ${title.toLowerCase()}`}
                    aria-label={`Search ${title.toLowerCase()}`}
                    value={search}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                    data-attr="library-search"
                />
                {loadFailed && !visibleObjects.length ? (
                    <Item variant="outline" tone="destructive" role="alert">
                        <ItemContent>
                            <ItemTitle>Couldn’t load your library</ItemTitle>
                            <ItemDescription>Try again, and if it keeps happening contact support.</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                size="sm"
                                loading={objectsLoading}
                                onClick={() => loadObjects()}
                                data-attr="library-retry"
                            >
                                Try again
                            </Button>
                        </ItemActions>
                    </Item>
                ) : (
                    <Table fullWidth>
                        <TableHeader>
                            <TableRow>
                                <TableHead expand>Name</TableHead>
                                {!objectType && <TableHead>Type</TableHead>}
                                <TableHead align="right">Created</TableHead>
                            </TableRow>
                        </TableHeader>
                        {objectsLoading && !visibleObjects.length ? (
                            <TableEmpty>
                                <SkeletonText lines={4} />
                            </TableEmpty>
                        ) : !visibleObjects.length ? (
                            <TableEmpty>
                                <Text size="sm" variant="muted">
                                    {emptyMessage}
                                </Text>
                            </TableEmpty>
                        ) : (
                            <TableBody>
                                {visibleObjects.map((entry) => {
                                    const href = libraryObjectHref(entry)
                                    const name = libraryObjectName(entry)
                                    return (
                                        <TableRow key={entry.id}>
                                            <TableCell expand>
                                                <span className="flex min-w-0 items-center gap-2">
                                                    <span className="flex shrink-0">
                                                        {iconForType(entry.type as FileSystemIconType)}
                                                    </span>
                                                    {href ? (
                                                        <LinkPrimitive
                                                            to={href}
                                                            className="truncate font-medium hover:underline"
                                                            data-attr="library-object"
                                                        >
                                                            {name}
                                                        </LinkPrimitive>
                                                    ) : (
                                                        <span className="truncate font-medium">{name}</span>
                                                    )}
                                                </span>
                                            </TableCell>
                                            {!objectType && (
                                                <TableCell>
                                                    {objectTypeByValue[baseObjectType(entry.type)]?.label ??
                                                        baseObjectType(entry.type)}
                                                </TableCell>
                                            )}
                                            <TableCell align="right">
                                                {entry.created_at ? (
                                                    // The timezone label is shared app-wide, so it stays on LemonUI.
                                                    <span data-not-quill>
                                                        <TZLabel time={entry.created_at} />
                                                    </span>
                                                ) : null}
                                            </TableCell>
                                        </TableRow>
                                    )
                                })}
                            </TableBody>
                        )}
                    </Table>
                )}
                {hasMore && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-center"
                        loading={objectsLoading}
                        onClick={() => loadMoreObjects()}
                        data-attr="library-load-more"
                    >
                        Show more
                    </Button>
                )}
            </TodayQuillRoot>
        </SceneContent>
    )
}
