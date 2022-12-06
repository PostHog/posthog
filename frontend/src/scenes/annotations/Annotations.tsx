import { useValues, useActions } from 'kea'
import {
    annotationScopeToLevel,
    annotationScopeToName,
    annotationModalLogic,
    ANNOTATION_DAYJS_FORMAT,
} from './annotationModalLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { AnnotationScope, InsightShortId, AnnotationType } from '~/types'
import { SceneExport } from 'scenes/sceneTypes'
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
import { AnnotationModal } from './AnnotationModal'
import { shortTimeZone } from 'lib/utils'

export const scene: SceneExport = {
    component: Annotations,
    logic: annotationModalLogic,
}

export function Annotations(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { annotations, annotationsLoading, next, loadingNext, timezone } = useValues(annotationModalLogic)
    const { loadAnnotationsNext, openModalToCreateAnnotation, openModalToEditAnnotation } =
        useActions(annotationModalLogic)

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
            title: `Date and time (${shortTimeZone(timezone)})`,
            dataIndex: 'date_marker',
            render: function RenderDateMarker(_, annotation: AnnotationType): string {
                // Format marker. Minute precision is used, because that's as detailed as our graphs can be
                return annotation.date_marker.format(ANNOTATION_DAYJS_FORMAT)
            },
            sorter: (a, b) => a.date_marker.diff(b.date_marker),
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
                        <LemonTag className="uppercase">
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
            render: function RenderActions(_, annotation): JSX.Element {
                return (
                    <LemonButton
                        icon={<IconEdit />}
                        size="small"
                        type="tertiary"
                        status="stealth"
                        onClick={() => openModalToEditAnnotation(annotation)}
                    />
                )
            },
        },
    ]

    return (
        <>
            <PageHeader
                title="Annotations"
                caption={
                    <>
                        Annotations add time-specific context to insights and dashboards.
                        <br />
                        Manage all of this project's annotations from this page.
                    </>
                }
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="create-annotation"
                        onClick={() => openModalToCreateAnnotation()}
                    >
                        New annotation
                    </LemonButton>
                }
            />
            <LemonTable
                data-attr="annotations-table"
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
            <AnnotationModal />
        </>
    )
}
