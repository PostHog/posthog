import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayCreateObjectButton } from '~/layout/today/TodayCreateObjectButton'
import {
    baseObjectType,
    libraryObjectHref,
    libraryObjectName,
    todayLibraryLogic,
} from '~/layout/today/todayLibraryLogic'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

/** Saved objects in the main area, filtered by the type picked in the Library sub-nav. */
export function TodayLibrary(): JSX.Element {
    const { objectType, objectTypeByValue, visibleObjects, objectsLoading, loadFailed, search, hasMore } =
        useValues(todayLibraryLogic)
    const { setSearch, loadObjects, loadMoreObjects } = useActions(todayLibraryLogic)
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
                            <Link to={href} className="truncate font-semibold" data-attr="today-library-object">
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
        <div className="Today__page mx-auto w-full max-w-[960px] px-6 py-12 flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                    <div className="Today__label">Library</div>
                    <h1 className="text-2xl font-semibold mt-1 mb-0">{title}</h1>
                </div>
                {selectedType && (
                    <TodayCreateObjectButton
                        objectType={selectedType.value}
                        label={`New ${selectedType.label.toLowerCase()}`}
                    />
                )}
            </div>
            <LemonInput
                type="search"
                placeholder={`Search ${title.toLowerCase()}`}
                value={search}
                onChange={setSearch}
                data-attr="today-library-search"
                fullWidth
            />
            {loadFailed && !visibleObjects.length ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadObjects() }}>
                    Your library didn’t load.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={visibleObjects}
                    columns={columns}
                    loading={objectsLoading}
                    rowKey="id"
                    emptyState={
                        search
                            ? 'Nothing matches that search.'
                            : selectedType
                              ? `No ${selectedType.pluralLabel.toLowerCase()} yet. Create one to see it here.`
                              : 'Insights, dashboards, flags and everything else you save show up here.'
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
                        data-attr="today-library-load-more"
                    >
                        Show more
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
