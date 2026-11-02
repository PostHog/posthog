import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

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

    const columns: LemonTableColumns<FileSystemEntry> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, entry) => {
                const href = libraryObjectHref(entry)
                const name = libraryObjectName(entry)
                return (
                    <span className="flex items-center gap-2 min-w-0">
                        <span className="shrink-0 flex">{iconForType(entry.type as FileSystemIconType)}</span>
                        {href ? (
                            <Link to={href} className="truncate font-semibold" data-attr="library-object">
                                {name}
                            </Link>
                        ) : (
                            <span className="truncate font-semibold">{name}</span>
                        )}
                    </span>
                )
            },
        },
        ...(objectType
            ? []
            : [
                  {
                      title: 'Type',
                      key: 'type',
                      render: (_: unknown, entry: FileSystemEntry) =>
                          objectTypeByValue[baseObjectType(entry.type)]?.label ?? baseObjectType(entry.type),
                  },
              ]),
        {
            title: 'Created',
            key: 'created_at',
            align: 'right',
            render: (_, entry) => (entry.created_at ? <TZLabel time={entry.created_at} /> : null),
        },
    ]

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
                        <LibraryCreateButton
                            objectType={selectedType.value}
                            label={`New ${selectedType.label.toLowerCase()}`}
                        />
                    ) : undefined
                }
            />
            <LemonInput
                type="search"
                placeholder={`Search ${title.toLowerCase()}`}
                value={search}
                onChange={setSearch}
                data-attr="library-search"
                fullWidth
            />
            {loadFailed && !visibleObjects.length ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadObjects(), loading: objectsLoading }}
                >
                    Couldn’t load your library. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={visibleObjects}
                    columns={columns}
                    loading={objectsLoading}
                    rowKey="id"
                    emptyState={
                        hasMore
                            ? 'Nothing to show on the pages loaded so far. Select Show more to keep looking.'
                            : search
                              ? 'Nothing matches that search.'
                              : selectedType
                                ? `No ${selectedType.pluralLabel.toLowerCase()} yet. Create one to see it here.`
                                : 'Flags, experiments, cohorts and everything else you save show up here.'
                    }
                />
            )}
            {hasMore && (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={objectsLoading}
                        onClick={() => loadMoreObjects()}
                        data-attr="library-load-more"
                    >
                        Show more
                    </LemonButton>
                </div>
            )}
        </SceneContent>
    )
}
