import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { LazyTextContent } from 'lib/components/RichContentEditor/LazyRichContent'
import { TZLabel } from 'lib/components/TZLabel'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType, InsightShortId } from '~/types'

import { annotationScopeToName } from '../logics/annotationModalLogic'
import { annotationsLogic } from '../logics/annotationsLogic'
import { annotationScopeTooltip } from './annotationScopeTooltip'
import { ANNOTATION_SORT_KEYS, sortAnnotations } from './sortAnnotations'

type Columns = DataTableProps<AnnotationType, unknown>['columns']
type SortingState = NonNullable<DataTableProps<AnnotationType, unknown>['sorting']>

/** Quill version of the annotations list, with the same columns, sorting and "Load more" as the Lemon table. */
export function QuillAnnotationsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { annotations, filteredAnnotations, annotationsLoading } = useValues(annotationsLogic)
    const { setScope } = useActions(annotationsLogic)
    const { loadingNext, next } = useValues(annotationsModel)
    const { loadAnnotationsNext } = useActions(annotationsModel)
    // The Lemon table opens newest first and never clears its sort, so this one does the same.
    const [sorting, setSorting] = useState<SortingState>([{ id: 'date_marker', desc: true }])

    const columns = useMemo<Columns>(
        () => [
            {
                id: 'annotation',
                header: 'Annotation',
                meta: { expand: true },
                enableSorting: false,
                cell: ({ row }) => {
                    const annotation = row.original
                    return (
                        <Tooltip>
                            <TooltipTrigger render={<div className="flex min-w-0 items-center gap-1.5" />} delay={300}>
                                {annotation.emoji && (
                                    <span className="shrink-0 text-base leading-none">{annotation.emoji}</span>
                                )}
                                {/* line-clamp-2 must stay on its own element, because flex on the same element breaks the clamp */}
                                <div className="line-clamp-2 min-w-0 font-semibold">
                                    <Button
                                        variant="link-foreground"
                                        size="inline"
                                        nativeButton={false}
                                        left
                                        render={<LinkPrimitive to={urls.annotation(annotation.id)} />}
                                        className="whitespace-normal text-left"
                                    >
                                        {annotation.content ?? ''}
                                    </Button>
                                </div>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-96">
                                <LazyTextContent
                                    text={annotation.content ?? ''}
                                    data-attr="annotation-scene-comment-title-rendered-content"
                                />
                            </TooltipContent>
                        </Tooltip>
                    )
                },
            },
            {
                id: 'date_marker',
                accessorFn: ANNOTATION_SORT_KEYS.date_marker,
                header: 'Timestamp',
                sortDescFirst: true,
                cell: ({ row }) =>
                    row.original.date_marker ? (
                        <Text size="xs" className="whitespace-nowrap" render={<span />}>
                            <TZLabel time={row.original.date_marker} />
                        </Text>
                    ) : null,
            },
            {
                id: 'scope',
                accessorFn: ANNOTATION_SORT_KEYS.scope,
                header: 'Scope',
                cell: ({ row }) => {
                    const annotation = row.original
                    const scopeName = annotationScopeToName[annotation.scope]
                    return (
                        <Tooltip>
                            <TooltipTrigger render={<span className="inline-flex" />}>
                                <Badge className="uppercase">
                                    {annotation.scope === AnnotationScope.Insight ? (
                                        <LinkPrimitive
                                            to={urls.insightView(annotation.insight_short_id as InsightShortId)}
                                            target="_blank"
                                            className="flex items-center gap-1"
                                        >
                                            {scopeName}
                                            <IconOpenInNew />
                                        </LinkPrimitive>
                                    ) : (
                                        scopeName
                                    )}
                                </Badge>
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                {annotationScopeTooltip(annotation, currentTeam?.name, currentOrganization?.name)}
                            </TooltipContent>
                        </Tooltip>
                    )
                },
            },
            {
                id: 'created_by',
                accessorFn: ANNOTATION_SORT_KEYS.created_by,
                header: 'Created by',
                cell: ({ row }) => {
                    const { created_by, creation_type } = row.original
                    return (
                        <div className="whitespace-nowrap">
                            <ProfilePicture
                                user={creation_type === 'GIT' ? { first_name: 'GitHub Actions' } : created_by}
                                showName
                                size="md"
                                type={creation_type === 'GIT' ? 'bot' : 'person'}
                            />
                        </div>
                    )
                },
            },
            {
                id: 'created_at',
                accessorFn: ANNOTATION_SORT_KEYS.created_at,
                header: 'Created',
                sortDescFirst: true,
                cell: ({ row }) =>
                    row.original.created_at ? (
                        <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                            <TZLabel time={row.original.created_at} />
                        </Text>
                    ) : null,
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <Button
                        size="icon-sm"
                        tooltip="Edit"
                        aria-label={`Edit ${row.original.content ?? 'annotation'}`}
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.annotation(row.original.id)} />}
                    >
                        <IconPencil />
                    </Button>
                ),
            },
        ],
        [currentTeam?.name, currentOrganization?.name]
    )

    const sortedAnnotations = useMemo(
        () => sortAnnotations(filteredAnnotations, sorting),
        [filteredAnnotations, sorting]
    )

    if (annotationsLoading && annotations.length === 0) {
        return <QuillTableSkeleton label="Loading annotations" />
    }
    if (annotations.length === 0) {
        return (
            <Empty data-attr="annotations-empty">
                <EmptyHeader>
                    <EmptyTitle>No annotations yet</EmptyTitle>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <div className="flex flex-col gap-4">
            {filteredAnnotations.length === 0 ? (
                <Empty data-attr="annotations-empty">
                    <EmptyHeader>
                        <EmptyTitle>No annotations in this scope</EmptyTitle>
                        <EmptyDescription>Pick another scope to see more annotations.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={() => setScope(null)}>
                            Clear filters
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : (
                <Card size="sm" flush className="pt-0">
                    <div data-attr="annotations-table">
                        <DataTable
                            columns={columns}
                            data={sortedAnnotations}
                            fullWidth
                            size="sm"
                            getRowId={(annotation) => String(annotation.id)}
                            sorting={sorting}
                            onSortingChange={(next) => {
                                // Like the Lemon table's `noSortingCancellation`, a third click flips the order back.
                                setSorting(
                                    next.length > 0 ? next : sorting.map((sort) => ({ ...sort, desc: !sort.desc }))
                                )
                            }}
                        />
                    </div>
                </Card>
            )}
            {next && (
                <div className="flex justify-center">
                    <Button variant="primary" loading={loadingNext} onClick={() => loadAnnotationsNext()}>
                        Load more annotations
                    </Button>
                </div>
            )}
        </div>
    )
}
