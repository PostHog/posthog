import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Button, DataTable, DataTableProps, Empty, EmptyHeader, EmptyTitle, SkeletonText, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import type { ActionReferenceApi } from '../generated/api.schemas'
import { ActionEditLogicProps, REFERENCE_TYPE_LABELS, actionEditLogic } from '../logics/actionEditLogic'
import { QuillActionSection } from './QuillActionSection'

const PAGE_SIZE = 10

export function QuillActionReferences({ logicProps }: { logicProps: ActionEditLogicProps }): JSX.Element {
    const { filteredReferences, referencesSearch, referencesLoading } = useValues(actionEditLogic(logicProps))
    const { setReferencesSearch } = useActions(actionEditLogic(logicProps))

    const columns = useMemo<DataTableProps<ActionReferenceApi, unknown>['columns']>(
        () => [
            {
                id: 'name',
                accessorKey: 'name',
                header: 'Name',
                meta: { expand: true },
                cell: ({ row }) => (
                    <Button
                        variant="link-foreground"
                        size="sm"
                        left
                        render={<LinkPrimitive to={row.original.url} />}
                        className="min-w-0 max-w-full"
                    >
                        <span className="truncate">{row.original.name}</span>
                    </Button>
                ),
            },
            {
                id: 'type',
                accessorFn: (reference) => REFERENCE_TYPE_LABELS[reference.type] ?? reference.type,
                header: 'Type',
            },
            {
                id: 'created_by',
                header: 'Created by',
                enableSorting: false,
                cell: ({ row }) => <AnalyticsOwner owner={row.original.created_by} className="max-w-40" />,
            },
            {
                id: 'created_at',
                accessorKey: 'created_at',
                header: 'Created',
                sortDescFirst: true,
                cell: ({ row }) =>
                    row.original.created_at ? (
                        <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                            <TZLabel time={row.original.created_at} />
                        </Text>
                    ) : null,
            },
        ],
        []
    )

    return (
        <QuillActionSection
            title="Used in analytics"
            description="Insights, experiments, and cohorts that reference this action."
        >
            <AnalyticsSearchInput
                value={referencesSearch}
                onChange={setReferencesSearch}
                label="Search references"
                placeholder="Search..."
                dataAttr="action-references-search"
                className="w-72 max-w-full"
            />
            {referencesLoading && !filteredReferences.length ? (
                <SkeletonText lines={3} />
            ) : (
                <DataTable
                    columns={columns}
                    data={filteredReferences}
                    fullWidth
                    size="sm"
                    pageSize={PAGE_SIZE}
                    getRowId={(reference) => `${reference.type}-${reference.id}`}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>
                                    {referencesSearch
                                        ? 'No references match this search.'
                                        : 'No insights, experiments, or cohorts use this action yet.'}
                                </EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    }
                />
            )}
        </QuillActionSection>
    )
}
