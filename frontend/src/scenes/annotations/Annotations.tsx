import React from 'react'
import { useValues, useActions } from 'kea'
import { annotationsTableLogic } from './logic'
import { PageHeader } from 'lib/components/PageHeader'
import { AnnotationType, AnnotationScope, InsightShortId } from '~/types'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { IconEdit, IconOpenInNew } from 'lib/components/icons'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { Tooltip } from 'lib/components/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'

export const scene: SceneExport = {
    component: Annotations,
    logic: annotationsTableLogic,
}

const annotationScopeToName: Record<AnnotationScope, string> = {
    [AnnotationScope.Insight]: 'Insight',
    [AnnotationScope.Project]: 'Project',
    [AnnotationScope.Organization]: 'Organization',
}

const annotationScopeToLevel: Record<AnnotationScope, number> = {
    [AnnotationScope.Insight]: 0,
    [AnnotationScope.Project]: 1,
    [AnnotationScope.Organization]: 2,
}

export function Annotations(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { annotations, annotationsLoading, next, loadingNext } = useValues(annotationsTableLogic)
    const { loadAnnotationsNext } = useActions(annotationsTableLogic)

    const columns: LemonTableColumns<AnnotationType> = [
        {
            title: 'Annotation',
            key: 'annotation',
            width: '30%',
            render: function RenderAnnotation(_, annotation: AnnotationType): JSX.Element {
                return <div className="ph-no-capture">{annotation.content}</div>
            },
        },
        {
            title: 'Date and time',
            dataIndex: 'date_marker',
            render: function RenderDateMarker(_, annotation: AnnotationType): string {
                // Format marker. Minute precision is used, because that's as detailed as our graphs can be
                return dayjs(annotation.date_marker).format('MMMM DD, YYYY h:mm A')
            },
            sorter: (a, b) => dayjs(a.date_marker).diff(b.date_marker),
        },
        {
            title: 'Scope',
            key: 'scope',
            render: function RenderType(_, annotation: AnnotationType): JSX.Element {
                const scopeName = annotationScopeToName[annotation.scope]
                const tooltip =
                    annotation.scope === AnnotationScope.Insight
                        ? `This annotation only applies to the "${annotation.insight_name}" insight`
                        : annotation.scope === AnnotationScope.Project
                        ? `This annotation applies to all insights in the ${currentTeam?.name} project`
                        : `This annotation applies to all insights in the ${currentOrganization?.name} organization`
                return (
                    <Tooltip title={tooltip} placement="right">
                        <LemonTag>
                            {annotation.scope === AnnotationScope.Insight ? (
                                <Link
                                    to={urls.insightView(annotation.insight_short_id as InsightShortId)}
                                    className="flex items-center"
                                    target="_blank"
                                >
                                    {scopeName}
                                    <IconOpenInNew className="ml-1" />
                                </Link>
                            ) : (
                                scopeName
                            )}
                        </LemonTag>
                    </Tooltip>
                )
            },
            sorter: (a, b) => annotationScopeToLevel[a.scope] - annotationScopeToLevel[b.scope],
        },
        createdByColumn() as LemonTableColumn<AnnotationType, keyof AnnotationType | undefined>,
        createdAtColumn() as LemonTableColumn<AnnotationType, keyof AnnotationType | undefined>,
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(): JSX.Element {
                return <LemonButton icon={<IconEdit />} size="small" type="tertiary" status="stealth" />
            },
        },
    ]

    return (
        <>
            <PageHeader
                title="Annotations"
                caption="Here you can add organization- and project-wide annotations. Dashboard-specific ones can be added directly in the dashboard."
                buttons={
                    <LemonButton type="primary" data-attr="create-annotation" data-tooltip="annotations-new-button">
                        New annotation
                    </LemonButton>
                }
            />
            <LemonTable
                data-attr="annotations-table"
                data-tooltip="annotations-table"
                rowKey="id"
                dataSource={annotations}
                columns={columns}
                defaultSorting={{
                    columnKey: 'date_marker',
                    order: -1,
                }}
                noSortingCancellation
                loading={annotationsLoading}
                emptyState="No annotations yet"
            />
            {next && (
                <div className="flex justify-center mt-6">
                    <LemonButton
                        type="primary"
                        loading={loadingNext}
                        onClick={(): void => {
                            loadAnnotationsNext()
                        }}
                    >
                        Load more annotations
                    </LemonButton>
                </div>
            )}
        </>
    )
}
