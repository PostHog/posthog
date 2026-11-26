import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil, IconSearch, IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    Card,
    DataTable,
    DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { Variable } from '~/queries/nodes/DataVisualization/types'

import { DELETE_VARIABLE_DESCRIPTION, VARIABLE_TYPE_LABELS, formatVariableReference } from './constants'
import { sqlVariablesLogic } from './sqlVariablesLogic'

const PAGE_SIZE = 25

type Columns = DataTableProps<Variable, unknown>['columns']

function DefaultValue({ value }: { value: Variable['default_value'] }): JSX.Element {
    if (value === undefined || value === null || value === '') {
        return (
            <Text size="xs" variant="muted" render={<span />}>
                —
            </Text>
        )
    }
    return (
        <Text size="xs" render={<span />}>
            {typeof value === 'boolean' ? (value ? 'true' : 'false') : String(value)}
        </Text>
    )
}

export function QuillSqlVariablesTable(): JSX.Element {
    const { variables, filteredVariables, variablesLoading, searchTerm } = useValues(sqlVariablesLogic)
    const { deleteVariable, setSearchTerm } = useActions(sqlVariablesLogic)
    // The variable stays set after the dialog closes, so its name holds while the dialog animates out.
    const [pendingDelete, setPendingDelete] = useState<Variable | null>(null)
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

    // The Lemon table sorts by name until the user picks a column, so the rows start in that order here too.
    const sortedVariables = useMemo(
        () => [...filteredVariables].sort((a, b) => a.name.localeCompare(b.name)),
        [filteredVariables]
    )

    const columns = useMemo<Columns>(
        () => [
            {
                id: 'name',
                accessorKey: 'name',
                header: 'Name',
                meta: { expand: true },
                sortingFn: (a, b) => a.original.name.localeCompare(b.original.name),
                cell: ({ row }) => (
                    // The table pulls a borderless Button that sits directly in a cell 0.5rem to the left, to offset
                    // its padding. This inline link has no padding, so the wrapper keeps it in line with the header.
                    <div className="flex min-w-0">
                        <Button
                            variant="link-foreground"
                            size="inline"
                            nativeButton={false}
                            left
                            render={<LinkPrimitive to={urls.variableEdit(row.original.id)} />}
                            className="min-w-0 max-w-full font-semibold"
                        >
                            <span className="truncate">{row.original.name}</span>
                        </Button>
                    </div>
                ),
            },
            {
                id: 'code_name',
                accessorKey: 'code_name',
                header: () => (
                    <Tooltip>
                        <TooltipTrigger render={<span />}>Code name</TooltipTrigger>
                        <TooltipContent>Use this to reference the variable in your SQL query</TooltipContent>
                    </Tooltip>
                ),
                sortingFn: (a, b) => a.original.code_name.localeCompare(b.original.code_name),
                cell: ({ row }) => (
                    <Badge className="font-mono">{formatVariableReference(row.original.code_name)}</Badge>
                ),
            },
            {
                id: 'type',
                accessorKey: 'type',
                header: 'Type',
                sortingFn: (a, b) => a.original.type.localeCompare(b.original.type),
                cell: ({ row }) => <Badge>{VARIABLE_TYPE_LABELS[row.original.type]}</Badge>,
            },
            {
                id: 'default_value',
                header: 'Default value',
                cell: ({ row }) => <DefaultValue value={row.original.default_value} />,
            },
            {
                id: 'actions',
                header: '',
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <div className="flex justify-end gap-1">
                        <Button
                            size="icon-sm"
                            tooltip="Edit"
                            aria-label={`Edit ${row.original.name}`}
                            render={<LinkPrimitive to={urls.variableEdit(row.original.id)} />}
                        >
                            <IconPencil />
                        </Button>
                        <Button
                            variant="destructive-outline"
                            size="icon-sm"
                            tooltip="Delete"
                            aria-label={`Delete ${row.original.name}`}
                            onClick={() => {
                                setPendingDelete(row.original)
                                setDeleteDialogOpen(true)
                            }}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                ),
            },
        ],
        []
    )

    const renderBody = (): JSX.Element => {
        if (variablesLoading && variables.length === 0) {
            return <QuillTableSkeleton label="Loading variables" />
        }
        if (variables.length === 0) {
            return (
                <Empty data-attr="sql-variables-empty">
                    <EmptyHeader>
                        <EmptyTitle>No variables yet</EmptyTitle>
                        <EmptyDescription>Create your first variable to get started.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )
        }
        if (filteredVariables.length === 0) {
            return (
                <Empty data-attr="sql-variables-empty">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconSearch />
                        </EmptyMedia>
                        <EmptyTitle>No variables match your search</EmptyTitle>
                        <EmptyDescription>Try a different search.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={() => setSearchTerm('')}>
                            Clear search
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <Card size="sm" flush className="pt-0">
                <div data-attr="sql-variables-table">
                    <DataTable
                        columns={columns}
                        data={sortedVariables}
                        fullWidth
                        size="sm"
                        pageSize={PAGE_SIZE}
                        getRowId={(variable) => variable.id}
                    />
                </div>
            </Card>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <AnalyticsSearchInput
                value={searchTerm}
                onChange={setSearchTerm}
                label="Search variables"
                placeholder="Search variables"
                dataAttr="sql-variables-search"
                className="w-72 max-w-full"
            />
            {renderBody()}
            <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{`Delete variable "${pendingDelete?.name}"?`}</AlertDialogTitle>
                        <AlertDialogDescription>{DELETE_VARIABLE_DESCRIPTION}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={() => {
                                if (pendingDelete) {
                                    deleteVariable(pendingDelete.id)
                                }
                                setDeleteDialogOpen(false)
                            }}
                        >
                            Delete variable
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    )
}
