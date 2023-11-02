import { useValues, useActions } from 'kea'
import {
    annotationScopeToLevel,
    annotationScopeToName,
    annotationModalLogic,
    ANNOTATION_DAYJS_FORMAT,
} from './annotationModalLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { AnnotationScope, InsightShortId, AnnotationType, ProductKey } from '~/types'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { IconEdit } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { AnnotationModal } from './AnnotationModal'
import { shortTimeZone } from 'lib/utils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { MicrophoneHog } from 'lib/components/hedgehogs'

export const scene: SceneExport = {
    component: Annotations,
    logic: annotationModalLogic,
}

export function Annotations(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        annotations,
        annotationsLoading,
        next,
        loadingNext,
        timezone,
        shouldShowEmptyState,
        shouldShowProductIntroduction,
    } = useValues(annotationModalLogic)
    const { loadAnnotationsNext, openModalToCreateAnnotation } = useActions(annotationModalLogic)

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
            title: `Date and time (${shortTimeZone(timezone)})`,
            dataIndex: 'date_marker',
            render: function RenderDateMarker(_, annotation: AnnotationType): string {
                // Format marker. Minute precision is used, because that's as detailed as our graphs can be
                return annotation.date_marker?.format(ANNOTATION_DAYJS_FORMAT) || ''
            },
            sorter: (a, b) => a.date_marker?.diff(b.date_marker) || 1,
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
                                    targetBlankIcon
                                >
                                    {scopeName}
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
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: function Render(_: any, item) {
                const { created_by, creation_type } = item
                return (
                    <div className="flex flex-row items-center">
                        <ProfilePicture
                            name={creation_type === 'GIT' ? 'GitHub Actions' : created_by?.first_name}
                            email={creation_type === 'GIT' ? undefined : created_by?.email}
                            showName
                            size="md"
                            type={creation_type === 'GIT' ? 'bot' : 'person'}
                        />
                    </div>
                )
            },
            sorter: (a, b) =>
                (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                    b.created_by?.first_name || b.created_by?.email || ''
                ),
        },
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
                        to={urls.annotation(annotation.id)}
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
                    !shouldShowEmptyState && !shouldShowProductIntroduction ? (
                        <>
                            Annotations allow you to mark when certain changes happened so you can easily see how they
                            impacted your metrics.
                        </>
                    ) : null
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
            <div data-attr={'annotations-content'}>
                {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                    <div className="mt-4">
                        <ProductIntroduction
                            productName="Annotations"
                            productKey={ProductKey.ANNOTATIONS}
                            thingName="annotation"
                            description="Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics."
                            docsURL="https://posthog.com/docs/data/annotations"
                            action={() => openModalToCreateAnnotation()}
                            isEmpty={annotations.length === 0}
                            customHog={MicrophoneHog}
                        />
                    </div>
                )}
                {!shouldShowEmptyState && (
                    <>
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
                    </>
                )}
            </div>
            <AnnotationModal />
        </>
    )
}
