import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSearch } from '@posthog/icons'
import {
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Field,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemContent,
    ItemTitle,
    Skeleton,
} from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'

import type { TagDefinitionApi } from '~/generated/core/api.schemas'

import { DeleteTagModalQuill } from './DeleteTagModalQuill'
import { MergeTagModalQuill } from './MergeTagModalQuill'
import { RenameTagModalQuill } from './RenameTagModalQuill'
import { TAG_PAGE_SIZE, TagOrdering, tagsLogic } from './tagsLogic'

export function TagsTableQuill(): JSX.Element {
    const { tagPage, tagPageLoading, search, page, ordering, listError, mutationLoading } = useValues(tagsLogic)
    const { setSearch, setPage, setOrdering, loadTagDefinitions, openRename, openMerge, openDelete } =
        useActions(tagsLogic)
    const pageCount = Math.max(1, Math.ceil((tagPage?.count ?? 0) / TAG_PAGE_SIZE))
    const columns: ColumnDef<TagDefinitionApi>[] = [
        {
            accessorKey: 'name',
            header: 'Name',
            meta: { expand: true },
            cell: ({ row }) => (
                <span className="block max-w-64 truncate" title={row.original.name}>
                    {row.original.name}
                </span>
            ),
        },
        { accessorKey: 'usage_count', header: 'Used by', meta: { align: 'right' } },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            cell: ({ row: { original: tag } }) => (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label={`Actions for ${tag.name}`}
                                tooltip={`Actions for ${tag.name}`}
                                disabledReason={
                                    mutationLoading || tagPageLoading
                                        ? 'Wait for the current request to finish.'
                                        : undefined
                                }
                                data-attr="tag-management-actions"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => openMerge(tag)}>Merge into another tag</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => openRename(tag)}>Rename</DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            disabledReason={
                                tag.usage_count ? 'This tag is in use. Merge it into another tag instead.' : undefined
                            }
                            onClick={() => openDelete(tag)}
                        >
                            Delete unused tag
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ),
        },
    ]

    return (
        <section className="flex flex-col gap-3" aria-label="Tags" data-quill>
            <Field className="w-full @min-[40rem]/main-content:w-72">
                <FieldLabel className="sr-only" htmlFor="tag-management-search">
                    Search tags
                </FieldLabel>
                <InputGroup size="sm">
                    <InputGroupAddon>
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        id="tag-management-search"
                        type="search"
                        placeholder="Search tags"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        data-attr="tag-management-search"
                    />
                </InputGroup>
            </Field>
            {listError ? (
                <Item tone="destructive">
                    <ItemContent>
                        <ItemTitle>{listError}</ItemTitle>
                        <Button variant="outline" onClick={() => loadTagDefinitions()}>
                            Try again
                        </Button>
                    </ItemContent>
                </Item>
            ) : tagPage === null ? (
                <Skeleton className="h-48 w-full" />
            ) : (
                <>
                    <DataTable
                        columns={columns}
                        data={tagPage.results}
                        fullWidth
                        size="sm"
                        getRowId={(tag) => tag.id}
                        sorting={[{ id: ordering.replace('-', ''), desc: ordering.startsWith('-') }]}
                        onSortingChange={(sorting) =>
                            setOrdering(`${sorting[0]?.desc ? '-' : ''}${sorting[0]?.id ?? 'name'}` as TagOrdering)
                        }
                        empty={
                            page > 1
                                ? 'No tags on this page.'
                                : search
                                  ? 'No tags match your search.'
                                  : 'No tags yet. Add tags to items in PostHog to see them here.'
                        }
                    />
                    {page > pageCount ? (
                        <Button
                            variant="outline"
                            onClick={() => setPage(page - 1)}
                            loading={tagPageLoading}
                            data-attr="tag-management-previous-page"
                        >
                            Previous page
                        </Button>
                    ) : tagPage.count > TAG_PAGE_SIZE ? (
                        <fieldset disabled={tagPageLoading} className="m-0 min-w-0 border-0 p-0">
                            <QuillTablePagination
                                currentPage={page}
                                pageCount={pageCount}
                                pageSize={TAG_PAGE_SIZE}
                                total={tagPage.count}
                                onPageChange={setPage}
                            />
                        </fieldset>
                    ) : null}
                </>
            )}
            <RenameTagModalQuill />
            <MergeTagModalQuill />
            <DeleteTagModalQuill />
        </section>
    )
}
