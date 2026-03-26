import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis, IconExternal, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonMenu, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HealthIssueCard } from '../components/HealthIssueCard'
import { severityColor, severityToTagType } from '../healthUtils'
import type { HealthIssueSeverity } from '../types'
import type { HealthCategoryDetailLogicProps, KindGroup } from './healthCategoryDetailLogic'
import { healthCategoryDetailLogic } from './healthCategoryDetailLogic'

export const scene: SceneExport<HealthCategoryDetailLogicProps> = {
    component: HealthCategoryDetailScene,
    logic: healthCategoryDetailLogic,
    paramsToProps: ({ params: { category } }) => ({ category: category ?? '' }),
}

function HealthCategoryDetailScene(): JSX.Element {
    const {
        categoryConfig,
        detailConfig,
        statusSummary,
        issuesByKind,
        healthIssuesLoading,
        healthIssues,
        showDismissed,
        isValidCategory,
    } = useValues(healthCategoryDetailLogic)
    const { refreshHealthData, setShowDismissed, dismissIssue, undismissIssue } = useActions(healthCategoryDetailLogic)

    if (!isValidCategory) {
        return <></>
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={categoryConfig?.label ?? 'Health detail'}
                description={categoryConfig?.description ?? null}
                resourceType={{ type: 'health' }}
            />

            <div className="flex flex-col gap-4 max-w-3xl">
                {healthIssuesLoading && !healthIssues ? (
                    <div className="flex flex-col gap-3">
                        <LemonSkeleton className="h-16 rounded" />
                        <LemonSkeleton className="h-16 rounded" />
                        <LemonSkeleton className="h-16 rounded" />
                    </div>
                ) : (
                    <>
                        <StatusBanner
                            isHealthy={statusSummary.isHealthy}
                            count={statusSummary.count}
                            worstSeverity={statusSummary.worstSeverity}
                            healthyDescription={categoryConfig?.healthyDescription}
                        />

                        {detailConfig?.guidance && (
                            <p className="text-sm text-secondary mb-0">{detailConfig.guidance}</p>
                        )}

                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                {detailConfig?.deepDiveUrl && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconExternal />}
                                        to={detailConfig.deepDiveUrl}
                                    >
                                        {detailConfig.deepDiveLabel ?? 'View details'}
                                    </LemonButton>
                                )}
                                {detailConfig?.docsUrl && (
                                    <Link to={detailConfig.docsUrl} className="text-xs text-muted">
                                        Docs
                                    </Link>
                                )}
                            </div>
                            <div className="flex items-center gap-1">
                                <LemonButton
                                    icon={<IconRefresh />}
                                    type="tertiary"
                                    size="small"
                                    tooltip="Refresh"
                                    loading={healthIssuesLoading}
                                    onClick={() => refreshHealthData()}
                                />
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Show dismissed',
                                            icon: showDismissed ? <IconCheck /> : undefined,
                                            onClick: () => setShowDismissed(!showDismissed),
                                        },
                                    ]}
                                    placement="bottom-end"
                                >
                                    <LemonButton icon={<IconEllipsis />} type="tertiary" size="small" />
                                </LemonMenu>
                            </div>
                        </div>

                        {issuesByKind.length === 0 ? (
                            <LemonBanner type="success">
                                <p className="font-semibold mb-0">All healthy</p>
                                <p className="text-sm mt-1 mb-0">No active issues found in this category.</p>
                            </LemonBanner>
                        ) : (
                            <div className="flex flex-col gap-4">
                                {issuesByKind.map((group: KindGroup) => (
                                    <KindSection
                                        key={group.kind}
                                        group={group}
                                        onDismiss={dismissIssue}
                                        onUndismiss={undismissIssue}
                                    />
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}

function StatusBanner({
    isHealthy,
    count,
    worstSeverity,
    healthyDescription,
}: {
    isHealthy: boolean
    count: number
    worstSeverity: HealthIssueSeverity | null
    healthyDescription?: string
}): JSX.Element {
    if (isHealthy) {
        return (
            <div className="flex items-center gap-2 text-success text-sm">
                <IconCheck className="size-4" />
                <span>{healthyDescription ?? 'No issues'}</span>
            </div>
        )
    }

    return (
        <div className={`flex items-center gap-2 text-sm ${severityColor(worstSeverity!)}`}>
            <IconWarning className="size-4" />
            <span>
                {count} {count === 1 ? 'issue' : 'issues'}
            </span>
        </div>
    )
}

function KindSection({
    group,
    onDismiss,
    onUndismiss,
}: {
    group: KindGroup
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    return (
        <LemonCollapse
            defaultActiveKey={group.kind}
            panels={[
                {
                    key: group.kind,
                    header: (
                        <div className="flex items-center justify-between w-full pr-2">
                            <div className="flex items-center gap-2">
                                <span className="font-medium">{group.label}</span>
                                <span className="text-xs text-muted">({group.issues.length})</span>
                            </div>
                            <LemonTag type={severityToTagType(group.worstSeverity)} size="small">
                                {group.worstSeverity}
                            </LemonTag>
                        </div>
                    ),
                    content: (
                        <div className="divide-y divide-border -m-4">
                            {group.issues.map((issue) => (
                                <HealthIssueCard
                                    key={issue.id}
                                    issue={issue}
                                    onDismiss={onDismiss}
                                    onUndismiss={onUndismiss}
                                />
                            ))}
                        </div>
                    ),
                },
            ]}
        />
    )
}
