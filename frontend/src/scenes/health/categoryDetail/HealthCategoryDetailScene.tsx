import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis, IconExternal, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonMenu, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HealthIssueCard } from '../components/HealthIssueCard'
import { HealthShowMoreFooter } from '../components/HealthShowMoreFooter'
import { severityColor, severityToTagType } from '../healthUtils'
import type { HealthIssueSeverity } from '../types'
import type { CategoryDetailConfig } from './categoryDetailConfig'
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
        categoryIssues,
        healthIssuesLoading,
        healthIssues,
        showDismissed,
        isValidCategory,
        loadingMoreKind,
        nextKindWithMore,
    } = useValues(healthCategoryDetailLogic)
    const { refreshHealthData, setShowDismissed, snoozeIssue, dismissIssue, undismissIssue, loadMoreIssues } =
        useActions(healthCategoryDetailLogic)

    if (!isValidCategory) {
        return <></>
    }

    const ContentComponent = detailConfig?.contentComponent

    return (
        <SceneContent>
            <SceneTitleSection
                name={categoryConfig?.label ?? 'Health detail'}
                description={categoryConfig?.description ?? null}
                resourceType={{ type: 'health' }}
            />

            {!healthIssues ? (
                <LoadingSkeleton />
            ) : ContentComponent ? (
                <ContentComponent
                    issues={categoryIssues}
                    statusSummary={statusSummary}
                    isLoading={healthIssuesLoading}
                    onSnooze={snoozeIssue}
                    onDismiss={dismissIssue}
                    onUndismiss={undismissIssue}
                    onRefresh={refreshHealthData}
                    showDismissed={showDismissed}
                    onSetShowDismissed={setShowDismissed}
                    onLoadMore={nextKindWithMore ? () => loadMoreIssues(nextKindWithMore) : undefined}
                    isLoadingMore={loadingMoreKind !== null}
                    remainingCount={issuesByKind.find((group) => group.kind === nextKindWithMore)?.remaining ?? 0}
                />
            ) : (
                <GenericCategoryContent
                    statusSummary={statusSummary}
                    issuesByKind={issuesByKind}
                    healthyDescription={categoryConfig?.healthyDescription}
                    detailConfig={detailConfig}
                    showDismissed={showDismissed}
                    healthIssuesLoading={healthIssuesLoading}
                    onRefresh={refreshHealthData}
                    onSetShowDismissed={setShowDismissed}
                    onSnooze={snoozeIssue}
                    onDismiss={dismissIssue}
                    onUndismiss={undismissIssue}
                    loadingMoreKind={loadingMoreKind}
                    onLoadMore={loadMoreIssues}
                />
            )}
        </SceneContent>
    )
}

function LoadingSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 max-w-3xl">
            <LemonSkeleton className="h-16 rounded" />
            <LemonSkeleton className="h-16 rounded" />
            <LemonSkeleton className="h-16 rounded" />
        </div>
    )
}

function GenericCategoryContent({
    statusSummary,
    issuesByKind,
    healthyDescription,
    detailConfig,
    showDismissed,
    healthIssuesLoading,
    onRefresh,
    onSetShowDismissed,
    onSnooze,
    onDismiss,
    onUndismiss,
    loadingMoreKind,
    onLoadMore,
}: {
    statusSummary: { count: number; worstSeverity: HealthIssueSeverity | null; isHealthy: boolean }
    issuesByKind: KindGroup[]
    healthyDescription?: string
    detailConfig?: CategoryDetailConfig
    showDismissed: boolean
    healthIssuesLoading: boolean
    onRefresh: () => void
    onSetShowDismissed: (show: boolean) => void
    onSnooze: (id: string, duration: string) => void
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
    loadingMoreKind: string | null
    onLoadMore: (kind: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <StatusBanner
                isHealthy={statusSummary.isHealthy}
                count={statusSummary.count}
                worstSeverity={statusSummary.worstSeverity}
                healthyDescription={healthyDescription}
            />

            {detailConfig?.guidance && <p className="text-sm text-secondary mb-0">{detailConfig.guidance}</p>}

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
                        onClick={() => onRefresh()}
                    />
                    <LemonMenu
                        items={[
                            {
                                label: 'Show dismissed',
                                icon: showDismissed ? <IconCheck /> : undefined,
                                onClick: () => onSetShowDismissed(!showDismissed),
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
                            onSnooze={onSnooze}
                            onDismiss={onDismiss}
                            onUndismiss={onUndismiss}
                            loadingMore={loadingMoreKind === group.kind}
                            onLoadMore={() => onLoadMore(group.kind)}
                        />
                    ))}
                </div>
            )}
        </div>
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
        <div className={`flex items-center gap-2 text-sm ${worstSeverity ? severityColor(worstSeverity) : ''}`}>
            <IconWarning className="size-4" />
            <span>
                {count} {count === 1 ? 'issue' : 'issues'}
            </span>
        </div>
    )
}

function KindSection({
    group,
    onSnooze,
    onDismiss,
    onUndismiss,
    loadingMore,
    onLoadMore,
}: {
    group: KindGroup
    onSnooze: (id: string, duration: string) => void
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
    loadingMore: boolean
    onLoadMore: () => void
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
                                <span className="text-xs text-muted" translate="no">
                                    ({group.count})
                                </span>
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
                                    onSnooze={onSnooze}
                                    onDismiss={onDismiss}
                                    onUndismiss={onUndismiss}
                                />
                            ))}
                            {group.remaining > 0 && (
                                <div className="px-4 py-2">
                                    <HealthShowMoreFooter
                                        shown={group.issues.length}
                                        total={group.count}
                                        remaining={group.remaining}
                                        loading={loadingMore}
                                        onShowMore={onLoadMore}
                                    />
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
