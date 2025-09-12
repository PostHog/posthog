import { useActions, useValues } from 'kea'

import { IconNotification, IconPencil } from '@posthog/icons'
import { LemonSelect, Link } from '@posthog/lemon-ui'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { MicrophoneHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType, InsightShortId, ProductKey } from '~/types'

import { AnnotationModal } from './AnnotationModal'
import { annotationModalLogic, annotationScopeToLevel, annotationScopeToName } from './annotationModalLogic'
import { annotationScopesMenuOptions, annotationsLogic } from './annotationsLogic'

export function Annotations(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const { currentOrganization } = useValues(organizationLogic)

    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    const { filteredAnnotations, shouldShowEmptyState, annotationsLoading, scope } = useValues(annotationsLogic)
    const { setScope } = useActions(annotationsLogic)

    const { loadingNext, next } = useValues(annotationsModel)
    const { loadAnnotationsNext } = useActions(annotationsModel)

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    const columns: LemonTableColumns<AnnotationType> = [
        {
            title: 'Annotation',
            key: 'annotation',
            width: '30%',
            render: function RenderAnnotation(_, annotation: AnnotationType): JSX.Element {
                let renderedContent = <>{annotation.content ?? ''}</>
                if ((annotation.content || '').trim().length > 30) {
                    renderedContent = (
                        <Tooltip
                            title={
                                <TextContent
                                    text={annotation.content ?? ''}
                                    data-attr="annotation-scene-comment-title-rendered-content"
                                />
                            }
                        >
                            {(annotation.content ?? '').slice(0, 27) + '...'}
                        </Tooltip>
                    )
                }
                return (
                    <div className="font-semibold">
                        <Link subtle to={urls.annotation(annotation.id)}>
                            {renderedContent}
                        </Link>
                    </div>
                )
            },
        },
        {
            title: `Timestamp`,
            dataIndex: 'date_marker',
            render: function RenderDateMarker(_, annotation: AnnotationType): JSX.Element | null {
                return annotation.date_marker ? <TZLabel time={annotation.date_marker} /> : null
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
                        : annotation.scope === AnnotationScope.Dashboard
                          ? `This annotation applies to all insights on the ${annotation.dashboard_name} dashboard`
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
                            user={creation_type === 'GIT' ? { first_name: 'GitHub Actions' } : created_by}
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
                return <LemonButton icon={<IconPencil />} size="small" to={urls.annotation(annotation.id)} />
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Annotations"
                description="Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics."
                resourceType={{
                    type: 'annotation',
                    forceIcon: <IconNotification />,
                }}
            />
            <SceneDivider />
            {newSceneLayout && (
                <div className="flex flex-row items-center gap-2 justify-end">
                    <div>Scope: </div>
                    <LemonSelect options={annotationScopesMenuOptions()} value={scope} onSelect={setScope} />
                </div>
            )}
            {!newSceneLayout && (
                <div className="flex flex-row items-center gap-2 justify-between">
                    <div>
                        Annotations allow you to mark when certain changes happened so you can easily see how they
                        impacted your metrics.
                    </div>
                    <div className="flex flex-row items-center gap-2">
                        <div>Scope: </div>
                        <LemonSelect options={annotationScopesMenuOptions()} value={scope} onSelect={setScope} />
                    </div>
                </div>
            )}
            <div data-attr="annotations-content">
                <div className={cn('mt-4', newSceneLayout && 'mb-0 empty:hidden')}>
                    <ProductIntroduction
                        productName="Annotations"
                        productKey={ProductKey.ANNOTATIONS}
                        thingName="annotation"
                        description="Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics."
                        docsURL="https://posthog.com/docs/data/annotations"
                        action={() => openModalToCreateAnnotation()}
                        isEmpty={shouldShowEmptyState}
                        customHog={MicrophoneHog}
                    />
                </div>
                {!shouldShowEmptyState && (
                    <>
                        <LemonTable
                            data-attr="annotations-table"
                            rowKey="id"
                            dataSource={filteredAnnotations}
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
        </SceneContent>
    )
}
