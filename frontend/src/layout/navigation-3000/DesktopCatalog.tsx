import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { getEntryAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { classicEmbedContext } from './classicEmbedContext'
import { LIBRARY_PAGE_SIZE, desktopCatalogLogic, desktopObjectHref } from './desktopCatalogLogic'
import { navigation3000Logic } from './navigationLogic'

export function DesktopCatalog(): JSX.Element {
    const { mobileLayout } = useValues(navigation3000Logic)
    const {
        objects,
        objectsLoading,
        error,
        objectTypes,
        objectType,
        search,
        page,
        order,
        toolCategories,
        visibleTools,
        objectView,
    } = useValues(desktopCatalogLogic)
    const { setFilters, loadObjects } = useActions(desktopCatalogLogic)
    const isTools = classicEmbedContext?.section === 'tools'
    const title = isTools ? 'Tools' : 'Library'

    return (
        <section className="@container/catalog flex flex-col gap-4 p-4 min-w-0" aria-label={title}>
            <div>
                <h1 className={cn('text-xl font-semibold mb-1', mobileLayout && 'pl-8')}>{title}</h1>
                <p className="text-secondary mb-0">
                    {isTools ? 'Explore, query, and manage your data.' : 'Find saved objects across your project.'}
                </p>
            </div>
            <div className="flex flex-wrap gap-2">
                {!isTools && objectView && (
                    <LemonButton type="secondary" to={desktopObjectHref(objectView)}>
                        Open product view
                    </LemonButton>
                )}
                <LemonInput
                    type="search"
                    aria-label={isTools ? 'Search tools' : 'Search library'}
                    placeholder={isTools ? 'Search tools' : 'Search library'}
                    value={search}
                    onChange={(value) => setFilters({ library_search: value })}
                    className="flex-1 min-w-40"
                />
                <LemonSelect
                    aria-label={isTools ? 'Category' : 'Object type'}
                    value={objectType}
                    onChange={(value) => setFilters({ library_type: value })}
                    options={[
                        { value: '', label: isTools ? 'All categories' : 'All types' },
                        ...(isTools ? toolCategories.map((value) => ({ value, label: value })) : objectTypes),
                    ]}
                />
                {!isTools && (
                    <LemonSelect
                        aria-label="Sort objects"
                        value={order}
                        onChange={(value) => setFilters({ library_order: value })}
                        options={[
                            { value: '-created_at', label: 'Newest first' },
                            { value: 'path', label: 'Folder and name' },
                        ]}
                    />
                )}
            </div>
            {isTools ? (
                <LemonTable
                    dataSource={visibleTools}
                    rowKey="path"
                    emptyState="No tools match. Change your search or category."
                    columns={[
                        {
                            title: 'Tool',
                            key: 'name',
                            render: (_, item) => (
                                <LemonButton
                                    fullWidth
                                    type="tertiary"
                                    to={desktopObjectHref(item)}
                                    icon={iconForType(item.iconType ?? (item.type as FileSystemIconType))}
                                >
                                    {item.displayLabel || item.path}
                                </LemonButton>
                            ),
                        },
                        {
                            title: 'Category',
                            key: 'category',
                            className: 'hidden @min-[40rem]/catalog:table-cell',
                            render: (_, item) => item.category || 'Tools',
                        },
                    ]}
                />
            ) : error ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadObjects }}>
                    Library did not load. Check your connection, then retry.
                </LemonBanner>
            ) : (
                <>
                    <LemonTable
                        dataSource={objectsLoading ? [] : objects.results}
                        rowKey="id"
                        loading={objectsLoading}
                        emptyState="No objects match. Change your search or type, or create an object in a product view."
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, item) => (
                                    <LemonButton
                                        fullWidth
                                        type="tertiary"
                                        to={desktopObjectHref(item)}
                                        disabledReason={
                                            getEntryAccessDisabledReason(item) ||
                                            (!desktopObjectHref(item)
                                                ? 'This object does not have a supported project page.'
                                                : undefined)
                                        }
                                        icon={iconForType(item.type as FileSystemIconType)}
                                    >
                                        <span className="truncate">
                                            {unescapePath(splitPath(item.path).pop() || item.path)}
                                        </span>
                                    </LemonButton>
                                ),
                            },
                            {
                                title: 'Type',
                                key: 'type',
                                render: (_, item) => (
                                    <LemonTag>
                                        {objectTypes.find((type) => type.value === item.type?.split('/')[0])?.label ||
                                            item.type ||
                                            'Object'}
                                    </LemonTag>
                                ),
                            },
                            {
                                title: 'Created',
                                key: 'created',
                                className: 'hidden @min-[40rem]/catalog:table-cell',
                                render: (_, item) =>
                                    item.created_at ? humanFriendlyDetailedTime(item.created_at) : '-',
                            },
                        ]}
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-secondary text-xs" role="status">
                            {objectsLoading ? 'Loading objects' : `${objects.count} objects`}
                        </span>
                        <div className="flex gap-2 items-center">
                            <LemonButton
                                disabledReason={
                                    objectsLoading ? 'Loading objects' : page === 0 ? 'First page' : undefined
                                }
                                onClick={() => setFilters({ library_page: page - 1 })}
                            >
                                Previous
                            </LemonButton>
                            <span className="text-xs">Page {page + 1}</span>
                            <LemonButton
                                disabledReason={
                                    objectsLoading
                                        ? 'Loading objects'
                                        : (page + 1) * LIBRARY_PAGE_SIZE >= objects.count
                                          ? 'Last page'
                                          : undefined
                                }
                                onClick={() => setFilters({ library_page: page + 1 })}
                            >
                                Next
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}
        </section>
    )
}
