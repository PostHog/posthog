import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonMenu, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import type { TagDefinitionApi } from '~/generated/core/api.schemas'

import { DeleteTagModal } from './DeleteTagModal'
import { MergeTagModal } from './MergeTagModal'
import { RenameTagModal } from './RenameTagModal'
import { TAG_PAGE_SIZE, TagOrdering, tagsLogic } from './tagsLogic'

export function TagsTableLemon(): JSX.Element {
    const { tagPage, tagPageLoading, search, page, ordering, listError, mutationLoading } = useValues(tagsLogic)
    const { setSearch, setPage, setOrdering, loadTagDefinitions, openRename, openMerge, openDelete } =
        useActions(tagsLogic)
    const columns: LemonTableColumns<TagDefinitionApi> = [
        {
            key: 'name',
            title: 'Name',
            dataIndex: 'name',
            sorter: true,
            render: (_, tag) => (
                <span className="block max-w-64 truncate" title={tag.name}>
                    {tag.name}
                </span>
            ),
        },
        { key: 'usage_count', title: 'Used by', dataIndex: 'usage_count', sorter: true },
        {
            key: 'actions',
            width: 0,
            render: (_, tag) => (
                <LemonMenu
                    items={[
                        { label: 'Merge into another tag', onClick: () => openMerge(tag) },
                        { label: 'Rename', onClick: () => openRename(tag) },
                        {
                            label: 'Delete unused tag',
                            status: 'danger',
                            disabledReason: tag.usage_count
                                ? 'This tag is in use. Merge it into another tag instead.'
                                : undefined,
                            onClick: () => openDelete(tag),
                        },
                    ]}
                >
                    <LemonButton
                        icon={<IconEllipsis />}
                        size="small"
                        aria-label={`Actions for ${tag.name}`}
                        data-attr="tag-management-actions"
                        disabledReason={
                            mutationLoading || tagPageLoading ? 'Wait for the current request to finish.' : undefined
                        }
                    />
                </LemonMenu>
            ),
        },
    ]

    return (
        <>
            <LemonInput
                className="max-w-80 mb-4"
                type="search"
                placeholder="Search tags"
                aria-label="Search tags"
                value={search}
                onChange={setSearch}
                data-attr="tag-management-search"
            />
            {listError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadTagDefinitions() }}>
                    {listError}
                </LemonBanner>
            ) : (
                <LemonTable<TagDefinitionApi>
                    data-attr="tag-management-table"
                    rowKey="id"
                    dataSource={tagPage?.results ?? []}
                    columns={columns}
                    loading={tagPageLoading || tagPage === null}
                    emptyState={
                        search
                            ? 'No tags match your search.'
                            : 'No tags yet. Add tags to items in PostHog to see them here.'
                    }
                    sorting={{ columnKey: ordering.replace('-', ''), order: ordering.startsWith('-') ? -1 : 1 }}
                    onSort={(sorting) =>
                        setOrdering(`${sorting?.order === -1 ? '-' : ''}${sorting?.columnKey ?? 'name'}` as TagOrdering)
                    }
                    pagination={{
                        controlled: true,
                        pageSize: TAG_PAGE_SIZE,
                        currentPage: page,
                        entryCount: tagPage?.count ?? 0,
                        onForward: tagPage?.next && !tagPageLoading ? () => setPage(page + 1) : undefined,
                        onBackward: page > 1 && !tagPageLoading ? () => setPage(page - 1) : undefined,
                    }}
                />
            )}
            <RenameTagModal />
            <MergeTagModal />
            <DeleteTagModal />
        </>
    )
}
