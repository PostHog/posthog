import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconArrowLeft,
    IconBug,
    IconCheck,
    IconChevronRight,
    IconFilter,
    IconGear,
    IconInfo,
    IconNotification,
    IconSearch,
    IconSparkles,
    IconWarning,
    IconX,
} from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonMenuOverlay,
    LemonSkeleton,
    LemonTabs,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { GraphsHog, PopUpBinocularsHog } from 'lib/components/hedgehogs'
import { NotFound } from 'lib/components/NotFound'
import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconArrowDown } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { statusBadgeColor } from 'scenes/debug/signals/helpers'
import type { SignalNode } from 'scenes/debug/signals/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { getReportPriorityLabel, inboxSceneLogic } from './inboxSceneLogic'
import { SignalCard } from './SignalCard'
import { SignalGraphTab } from './SignalGraphTab'
import { signalSourcesLogic } from './signalSourcesLogic'
import { SourcesModal } from './SourcesModal'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from './types'

function priorityTagType(priority: string): LemonTagType {
    switch (priority) {
        case 'P0':
            return 'danger'
        case 'P1':
            return 'warning'
        case 'P2':
            return 'caution'
        default:
            return 'muted'
    }
}

const PRIORITY_DESCRIPTIONS: Record<string, string> = {
    P0: 'P0: Critical, needs immediate attention',
    P1: 'P1: High priority, should be addressed soon',
    P2: 'P2: Medium priority, normal course of work',
    P3: 'P3: Low priority, address when convenient',
    P4: 'P4: Minimal priority, nice-to-have',
}

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

function ReportListItem({ report }: { report: SignalReport }): JSX.Element {
    const { selectedReportId } = useValues(inboxSceneLogic)
    const { setSelectedReportId } = useActions(inboxSceneLogic)

    const isSelected = selectedReportId === report.id
    const priority = getReportPriorityLabel(report)

    return (
        <Link
            to={urls.inbox(report.id)}
            onClick={
                isSelected
                    ? (e) => {
                          e.preventDefault()
                          setSelectedReportId(null)
                      }
                    : undefined
            }
            className={clsx(
                `w-full text-left px-3 py-2.5 flex items-start gap-2 cursor-pointer rounded border border-primary overflow-hidden`,
                isSelected ? 'bg-surface-primary' : 'bg-surface-secondary hover:bg-surface-tertiary'
            )}
        >
            <div className="flex-1 min-w-0">
                <h4 className="text-sm font-medium m-0 truncate flex-1">{report.title || <i>Untitled report</i>}</h4>

                {report.summary && (
                    <p
                        className={clsx(
                            'text-xs mt-0.5 m-0 line-clamp-2',
                            selectedReportId === report.id ? 'text-secondary' : 'text-tertiary'
                        )}
                    >
                        {report.summary}
                    </p>
                )}

                <div className="flex items-center gap-2 mt-1.5 text-xs text-tertiary whitespace-nowrap">
                    {priority && (
                        <Tooltip title={PRIORITY_DESCRIPTIONS[priority] ?? priority} delayMs={0}>
                            <LemonTag size="small" type={priorityTagType(priority)}>
                                {priority}
                            </LemonTag>
                        </Tooltip>
                    )}
                    {report.relevant_user_count !== null && report.relevant_user_count > 0 && (
                        <span>
                            {report.relevant_user_count} {report.relevant_user_count === 1 ? 'user' : 'users'}
                        </span>
                    )}
                    {report.signal_count > 0 && (
                        <span>
                            {report.signal_count} {report.signal_count === 1 ? 'signal' : 'signals'}
                        </span>
                    )}

                    <span className="grow shrink-0 flex justify-end">
                        <TZLabel title="Report last updated at" time={report.updated_at} />
                    </span>
                </div>
            </div>
        </Link>
    )
}

function ReportListSkeleton({ active = true }: { active?: boolean }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="px-3 py-2.5 rounded border border-primary">
                    <LemonSkeleton className="w-3/5 h-4" active={active} />
                    <LemonSkeleton className="w-full h-3 mt-1" active={active} />
                    <LemonSkeleton className="w-4/5 h-3 mt-0.5" active={active} />
                    <div className="flex items-center gap-2 mt-1.5">
                        <LemonSkeleton className="w-12 h-3" active={active} />
                        <LemonSkeleton className="w-14 h-3" active={active} />
                        <LemonSkeleton className="w-16 h-5 rounded-sm" active={active} />
                        <LemonSkeleton className="w-20 h-3 ml-auto" active={active} />
                    </div>
                </div>
            ))}
        </div>
    )
}

const STATUS_OPTIONS = Object.values(SignalReportStatus)

const STATUS_LABELS: Record<SignalReportStatus, string> = {
    [SignalReportStatus.POTENTIAL]: 'Potential',
    [SignalReportStatus.CANDIDATE]: 'Candidate',
    [SignalReportStatus.IN_PROGRESS]: 'In progress',
    [SignalReportStatus.PENDING_INPUT]: 'Pending input',
    [SignalReportStatus.READY]: 'Ready',
    [SignalReportStatus.FAILED]: 'Failed',
}

function StatusFilter(): JSX.Element {
    const { statusFilters } = useValues(inboxSceneLogic)
    const { setStatusFilters } = useActions(inboxSceneLogic)
    const [showPopover, setShowPopover] = useState(false)

    const isAllSelected = statusFilters.length === STATUS_OPTIONS.length
    const isSomeSelected = statusFilters.length > 0 && statusFilters.length < STATUS_OPTIONS.length

    const handleToggleAll = (): void => {
        if (isAllSelected || isSomeSelected) {
            setStatusFilters([])
        } else {
            setStatusFilters([...STATUS_OPTIONS])
        }
    }

    const handleToggleStatus = (status: SignalReportStatus): void => {
        const newStatuses = statusFilters.includes(status)
            ? statusFilters.filter((s) => s !== status)
            : [...statusFilters, status]
        setStatusFilters(newStatuses)
    }

    const displayValue = (): string => {
        if (statusFilters.length === 0 || isAllSelected) {
            return 'All statuses'
        }
        if (statusFilters.length === 1) {
            return STATUS_LABELS[statusFilters[0]]
        }
        return `${statusFilters.length} statuses`
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className="max-w-60 space-y-px p-1">
                    <LemonButton fullWidth size="small" onClick={handleToggleAll} className="justify-start">
                        <span className="flex items-center gap-2">
                            <LemonCheckbox checked={isAllSelected} className="pointer-events-none" />
                            <span className="font-semibold">
                                {isAllSelected || isSomeSelected ? 'Clear all' : 'Select all'}
                            </span>
                        </span>
                    </LemonButton>
                    <div className="border-t border-border my-1" />
                    {STATUS_OPTIONS.map((status) => (
                        <LemonButton
                            key={status}
                            fullWidth
                            size="small"
                            onClick={() => handleToggleStatus(status)}
                            className="justify-start"
                        >
                            <span className="flex items-center gap-2">
                                <LemonCheckbox
                                    checked={statusFilters.includes(status)}
                                    className="pointer-events-none"
                                />
                                <span className={clsx('w-2 h-2 rounded-full shrink-0', statusBadgeColor(status))} />
                                <span>{STATUS_LABELS[status]}</span>
                            </span>
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton type="secondary" size="small" icon={<IconFilter />} className="bg-surface-primary">
                {displayValue()}
            </LemonButton>
        </LemonDropdown>
    )
}

function ReportListPane(): JSX.Element {
    const {
        filteredReports,
        reportsLoading,
        searchQuery,
        reports,
        selectedReportId,
        shouldShowEnablingCtaOnMobile,
        statusFilters,
        reportsHasMore,
    } = useValues(inboxSceneLogic)
    const { hasNoSources } = useValues(signalSourcesLogic)
    const { setSearchQuery, loadMoreReports } = useActions(inboxSceneLogic)
    const { openSourcesModal } = useActions(signalSourcesLogic)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [isScrollable, setIsScrollable] = useState(false)

    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        const scrollabilityCheck = (): void => setIsScrollable(el.scrollHeight > el.clientHeight)
        scrollabilityCheck()
        const observer = new ResizeObserver(scrollabilityCheck)
        observer.observe(el)
        return () => observer.disconnect()
    }, [filteredReports.length])

    return (
        <ResizableElement
            defaultWidth={420}
            minWidth={280}
            maxWidth={600}
            borderPosition="right"
            onResize={() => {}}
            className={clsx(
                'flex-shrink-0 h-full',
                '@3xl/main-content-container:max-w-[50%] @3xl/main-content-container:border-r border-primary',
                (selectedReportId != null || shouldShowEnablingCtaOnMobile) &&
                    'hidden @3xl/main-content-container:block'
            )}
        >
            <div className="relative h-full">
                <LemonTableLoader loading={reportsLoading && reports.length > 0} placement="top" />
                <div ref={scrollRef} className="h-full p-3 overflow-y-auto">
                    <div className="flex gap-2 sticky top-0 z-10 mb-2">
                        <LemonInput
                            type="search"
                            placeholder="Search reports..."
                            prefix={<IconSearch />}
                            value={searchQuery}
                            onChange={setSearchQuery}
                            size="small"
                            fullWidth
                            disabledReason={
                                reportsLoading && reports.length === 0 && !searchQuery ? 'Loading reports...' : null
                            }
                        />
                        <StatusFilter />
                    </div>
                    {hasNoSources && filteredReports.length > 0 && (
                        <LemonBanner
                            type="info"
                            action={{ children: 'Set up sources now', onClick: openSourcesModal, icon: <IconGear /> }}
                            className="mb-2"
                        >
                            No signal sources enabled currently.
                            <br />
                            Set up sources to get new reports automatically.
                        </LemonBanner>
                    )}
                    <div className="flex flex-col gap-2">
                        {reportsLoading && reports.length === 0 ? (
                            <div className="relative overflow-hidden max-h-[calc(100vh-14rem)]">
                                <ReportListSkeleton />
                                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-primary to-transparent" />
                            </div>
                        ) : filteredReports.length === 0 ? (
                            <div className="relative overflow-hidden max-h-[calc(100vh-14rem)]">
                                <ReportListSkeleton active={false} />
                                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-primary to-transparent" />
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <p className="text-sm text-secondary font-medium m-0 cursor-default">
                                        {searchQuery || statusFilters.length > 0
                                            ? 'No reports matching filters.'
                                            : 'No reports yet.'}
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <>
                                {filteredReports.map((report: SignalReport) => (
                                    <ReportListItem key={report.id} report={report} />
                                ))}
                                {reportsHasMore && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        fullWidth
                                        center
                                        loading={reportsLoading}
                                        onClick={() => loadMoreReports()}
                                        className="mt-1"
                                    >
                                        Load more
                                    </LemonButton>
                                )}
                                {isScrollable && filteredReports.length > 0 && !reportsHasMore && (
                                    <Tooltip title="You've reached the end, friend." delayMs={0} placement="right">
                                        <PopUpBinocularsHog className="-mb-3.5 mt-1 w-16 self-center h-auto object-bottom" />
                                    </Tooltip>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
        </ResizableElement>
    )
}

function ImpactAssessmentBadge({ artefacts }: { artefacts: SignalReportArtefact[] }): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)

    const impactArtefact = artefacts.find((a) => a.type === 'impact_assessment')
    if (!impactArtefact) {
        return null
    }

    const content = impactArtefact.content as Record<string, unknown>
    const usersAffected = content.users_affected as number | null
    const activeUsers = content.active_users_in_period as number | null
    const userImpactRatio = content.user_impact_ratio as number | null
    const totalOccurrences = content.total_occurrences as number | undefined
    const externalReportCount = content.external_report_count as number | undefined
    const sourceProducts = content.source_products as string[] | undefined
    const crossProductCorroboration = content.cross_product_corroboration as boolean | undefined
    const strongestSeverity = content.strongest_external_severity as string | null
    const severityDetails = content.severity_details as string[] | undefined
    const signalsPerDay = content.signals_per_day as number | undefined

    const hasUserData = usersAffected != null
    const impactTagType: LemonTagType =
        userImpactRatio != null && userImpactRatio > 0.05
            ? 'danger'
            : userImpactRatio != null && userImpactRatio > 0.01
              ? 'warning'
              : 'muted'

    return (
        <div className="border rounded bg-surface-primary mb-3">
            <button
                type="button"
                className="w-full flex items-center gap-2 px-3 py-2 text-left cursor-pointer hover:bg-surface-tertiary rounded"
                onClick={() => setExpanded(!expanded)}
            >
                <span className="text-xs font-medium text-tertiary shrink-0">Impact:</span>
                <div className="flex items-center gap-1.5 flex-wrap flex-1">
                    {hasUserData ? (
                        <LemonTag size="small" type={impactTagType}>
                            {usersAffected.toLocaleString()} user{usersAffected !== 1 ? 's' : ''} affected
                            {userImpactRatio != null ? ` (${(userImpactRatio * 100).toFixed(1)}%)` : ''}
                        </LemonTag>
                    ) : null}
                    {totalOccurrences != null && totalOccurrences > 0 ? (
                        <LemonTag size="small" type="muted">
                            {totalOccurrences.toLocaleString()} occurrence{totalOccurrences !== 1 ? 's' : ''}
                        </LemonTag>
                    ) : null}
                    {externalReportCount != null && externalReportCount > 0 ? (
                        <LemonTag size="small" type="muted">
                            {externalReportCount} external report{externalReportCount !== 1 ? 's' : ''}
                        </LemonTag>
                    ) : null}
                    {crossProductCorroboration ? (
                        <LemonTag size="small" type="highlight">
                            Cross-product corroboration
                        </LemonTag>
                    ) : null}
                    {strongestSeverity ? (
                        <LemonTag
                            size="small"
                            type={
                                strongestSeverity === 'urgent'
                                    ? 'danger'
                                    : strongestSeverity === 'high'
                                      ? 'warning'
                                      : 'muted'
                            }
                        >
                            Severity: {strongestSeverity}
                        </LemonTag>
                    ) : null}
                </div>
                <IconChevronRight
                    className={clsx('size-4 text-tertiary transition-transform shrink-0', expanded && 'rotate-90')}
                />
            </button>
            {expanded && (
                <div className="px-3 pb-3 space-y-1 text-xs text-secondary">
                    {hasUserData && activeUsers != null ? (
                        <div>
                            <span className="font-medium text-tertiary">Users affected:</span>{' '}
                            {usersAffected.toLocaleString()} of {activeUsers.toLocaleString()} active users
                            {userImpactRatio != null ? ` (${(userImpactRatio * 100).toFixed(1)}%)` : ''}
                        </div>
                    ) : (
                        <div>
                            <span className="font-medium text-tertiary">Users affected:</span> unknown (no session
                            replay data)
                        </div>
                    )}
                    {totalOccurrences != null ? (
                        <div>
                            <span className="font-medium text-tertiary">Total occurrences:</span>{' '}
                            {totalOccurrences.toLocaleString()}
                        </div>
                    ) : null}
                    {sourceProducts && sourceProducts.length > 0 ? (
                        <div>
                            <span className="font-medium text-tertiary">Sources:</span> {sourceProducts.join(', ')}
                            {crossProductCorroboration ? ' (cross-product corroboration)' : ''}
                        </div>
                    ) : null}
                    {severityDetails && severityDetails.length > 0 ? (
                        <div>
                            <span className="font-medium text-tertiary">Severity details:</span>{' '}
                            {severityDetails.join('; ')}
                        </div>
                    ) : null}
                    {signalsPerDay != null && signalsPerDay > 0 ? (
                        <div>
                            <span className="font-medium text-tertiary">Trend:</span> {signalsPerDay.toFixed(1)}{' '}
                            signals/day
                            {signalsPerDay > 10
                                ? ' (active incident)'
                                : signalsPerDay > 3
                                  ? ' (elevated frequency)'
                                  : signalsPerDay < 0.5
                                    ? ' (chronic/slow accumulation)'
                                    : ''}
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    )
}

function JudgmentBadges({ artefacts }: { artefacts: SignalReportArtefact[] }): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)

    const safetyArtefact = artefacts.find((a) => a.type === 'safety_judgment')
    const actionabilityArtefact = artefacts.find((a) => a.type === 'actionability_judgment')

    if (!safetyArtefact && !actionabilityArtefact) {
        return null
    }

    const safetyContent = safetyArtefact?.content as Record<string, unknown> | undefined
    const actionabilityContent = actionabilityArtefact?.content as Record<string, unknown> | undefined

    const isSafe = safetyContent?.safe === true || safetyContent?.judgment === 'safe'
    const actionabilityChoice =
        (actionabilityContent?.choice as string) ?? (actionabilityContent?.judgment as string) ?? ''
    const actionabilityPriority = (actionabilityContent?.priority as string) ?? null

    return (
        <div className="border rounded bg-surface-primary mb-3">
            <button
                type="button"
                className="w-full flex items-center gap-2 px-3 py-2 text-left cursor-pointer hover:bg-surface-tertiary rounded"
                onClick={() => setExpanded(!expanded)}
            >
                <span className="text-xs font-medium text-tertiary shrink-0">LLM judgment:</span>
                <div className="flex items-center gap-1.5 flex-wrap flex-1">
                    {safetyArtefact && (
                        <LemonTag size="small" type={isSafe ? 'success' : 'danger'}>
                            {isSafe ? <IconCheck className="size-3" /> : <IconWarning className="size-3" />}
                            <span className="ml-0.5">{isSafe ? 'Safe' : 'Unsafe'}</span>
                        </LemonTag>
                    )}
                    {actionabilityArtefact && (
                        <LemonTag
                            size="small"
                            type={
                                actionabilityChoice === 'immediately_actionable'
                                    ? 'success'
                                    : actionabilityChoice === 'requires_human_input'
                                      ? 'caution'
                                      : 'muted'
                            }
                        >
                            {actionabilityChoice === 'immediately_actionable' ? (
                                <IconCheck className="size-3" />
                            ) : actionabilityChoice === 'requires_human_input' ? (
                                <IconWarning className="size-3" />
                            ) : (
                                <IconX className="size-3" />
                            )}
                            <span className="ml-0.5">
                                {actionabilityChoice === 'immediately_actionable'
                                    ? 'Immediately actionable'
                                    : actionabilityChoice === 'requires_human_input'
                                      ? 'Requires human input'
                                      : 'Not actionable'}
                            </span>
                        </LemonTag>
                    )}
                    {actionabilityPriority && (
                        <Tooltip
                            title={PRIORITY_DESCRIPTIONS[actionabilityPriority] ?? actionabilityPriority}
                            delayMs={0}
                        >
                            <LemonTag size="small" type={priorityTagType(actionabilityPriority)}>
                                {actionabilityPriority}
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
                <IconChevronRight
                    className={clsx('size-4 text-tertiary transition-transform shrink-0', expanded && 'rotate-90')}
                />
            </button>
            {expanded && (
                <div className="px-3 pb-3 space-y-2 text-sm text-secondary">
                    {safetyContent?.explanation ? (
                        <div>
                            <span className="font-medium text-xs text-tertiary">Safety:</span>
                            <LemonMarkdown className="mt-0.5">{String(safetyContent.explanation)}</LemonMarkdown>
                        </div>
                    ) : null}
                    {actionabilityContent?.explanation ? (
                        <div>
                            <span className="font-medium text-xs text-tertiary">Actionability:</span>
                            <LemonMarkdown className="mt-0.5">{String(actionabilityContent.explanation)}</LemonMarkdown>
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    )
}

function ReportDetailPane(): JSX.Element {
    const {
        selectedReport,
        shouldShowEnablingCtaOnMobile,
        activeDetailTab,
        selectedReportSignals,
        reportSignalsLoading,
    } = useValues(inboxSceneLogic)
    const { deleteReport, setActiveDetailTab } = useActions(inboxSceneLogic)
    const { hasNoSources } = useValues(signalSourcesLogic)
    const { openSourcesModal } = useActions(signalSourcesLogic)

    const baseClasses = 'flex-1 p-4 min-w-0 h-full self-start bg-surface-primary flex flex-col overflow-y-auto'

    if (!selectedReport) {
        return (
            <div
                className={clsx(
                    baseClasses,
                    `items-center justify-center p-8 cursor-default overflow-y-auto`,
                    // If user has no sources and no reports, always show the CTA area on mobile
                    !shouldShowEnablingCtaOnMobile && 'hidden @3xl/main-content-container:flex'
                )}
            >
                <GraphsHog className="w-36 mb-8" />
                <h3 className="text-xl font-bold mb-4 text-center">
                    Welcome to your Inbox
                    <sup>
                        <IconSparkles className="ml-0.5 text-ai" />
                    </sup>
                </h3>
                <div className="flex flex-col items-center gap-1.5 text-center text-xs text-secondary max-w-md leading-normal">
                    <div>
                        <strong>Background analysis of your data - while you sleep.</strong>
                        <br />
                        Powerful new analysis of sessions watches every recording for you. Integrations with external
                        sources on the way: issue trackers, support platforms, and more.
                    </div>
                    <IconArrowDown className="size-4 opacity-50" />
                    <div>
                        <strong>Inbox hands you ready-to-run fixes for real user problems.</strong>
                        <br />
                        Just execute the resulting prompt in your favorite coding agent. Each fix's report comes with
                        hard evidence and impact numbers.
                    </div>
                </div>
                {hasNoSources && (
                    <LemonButton type="primary" onClick={openSourcesModal} icon={<IconNotification />} className="mt-4">
                        Enable Inbox now
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <div className={baseClasses} key={selectedReport.id}>
            <div className="max-w-200 w-full border border-border-light rounded-lg mx-auto">
                {/* Header — always visible above tabs */}
                <div className="shrink-0 pt-6 pb-2 px-6">
                    <Link
                        to={urls.inbox()}
                        className="inline-flex items-center gap-1 text-sm text-secondary mb-4 @3xl/main-content-container:hidden"
                    >
                        <IconArrowLeft className="size-4" />
                        All reports
                    </Link>
                    <div>
                        <h2 className="text-xl font-medium mb-4 flex-1 leading-tight">
                            {selectedReport.title || 'Untitled report'}
                        </h2>
                        {selectedReport.summary && (
                            <LemonMarkdown className="text-sm text-secondary mb-0 mt-2 leading-normal">
                                {selectedReport.summary}
                            </LemonMarkdown>
                        )}
                        <div className="flex items-center gap-4 mt-4 text-xs text-tertiary cursor-default">
                            {selectedReport.relevant_user_count !== null && selectedReport.relevant_user_count > 0 && (
                                <span>
                                    {selectedReport.relevant_user_count}{' '}
                                    {selectedReport.relevant_user_count === 1 ? 'user' : 'users'}
                                </span>
                            )}
                            {selectedReport.signal_count > 0 && (
                                <span>
                                    {selectedReport.signal_count}{' '}
                                    {selectedReport.signal_count === 1 ? 'signal' : 'signals'}
                                </span>
                            )}
                            <Tooltip
                                title="Each signal adds weight to the report, depending on the signal's value and confidence. When a report reaches weight >=1.0, it's investigated by an AI agent."
                                delayMs={0}
                            >
                                Weight: {selectedReport.total_weight.toFixed(1)} <IconInfo className="size-3 ml-0.5" />
                            </Tooltip>
                            <span className="inline-flex items-center gap-1">
                                Created: <TZLabel time={selectedReport.created_at} />
                            </span>
                            <span className="inline-flex items-center gap-1">
                                Updated: <TZLabel time={selectedReport.updated_at} />
                            </span>
                            <More
                                overlay={
                                    <LemonMenuOverlay
                                        items={[
                                            {
                                                label: 'Delete report & signals',
                                                status: 'danger',
                                                onClick: () =>
                                                    LemonDialog.open({
                                                        title: `Delete report "${selectedReport.title}"?`,
                                                        className: 'max-w-120',
                                                        description:
                                                            'This will soft-delete all signals in this report and remove the report. Report deletion cannot be undone.',
                                                        primaryButton: {
                                                            children: 'Delete report & signals',
                                                            status: 'danger',
                                                            onClick: () => deleteReport(selectedReport.id),
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                        },
                                                    }),
                                            },
                                        ]}
                                    />
                                }
                            />
                        </div>
                    </div>
                </div>

                <LemonTabs
                    activeKey={activeDetailTab}
                    onChange={setActiveDetailTab}
                    barClassName="px-6 mb-0 [--color-border-primary:var(--border-light)]"
                    tabs={[
                        {
                            key: 'overview',
                            label: 'Overview',
                            content: (
                                <div className="p-6 max-w-200 w-full">
                                    {/* Impact assessment and judgment badges from artefacts */}
                                    {selectedReport.artefacts.length > 0 && (
                                        <>
                                            <ImpactAssessmentBadge artefacts={selectedReport.artefacts} />
                                            <JudgmentBadges artefacts={selectedReport.artefacts} />
                                        </>
                                    )}

                                    {/* Signal cards as primary content */}
                                    {reportSignalsLoading && !selectedReportSignals ? (
                                        <div className="items-center gap-2 text-sm text-tertiary py-4">
                                            <Spinner className="size-4" />
                                            Loading signals...
                                        </div>
                                    ) : selectedReportSignals && selectedReportSignals.length > 0 ? (
                                        <div className="space-y-3">
                                            {selectedReportSignals.map((signal: SignalNode) => (
                                                <SignalCard key={signal.signal_id} signal={signal} />
                                            ))}
                                        </div>
                                    ) : (
                                        <p className="text-sm text-tertiary m-0">No signals yet.</p>
                                    )}
                                </div>
                            ),
                        },
                        {
                            key: 'signals',
                            label: `Signals graph`,
                            content: (
                                <div className="flex-1 overflow-hidden">
                                    {reportSignalsLoading && !selectedReportSignals ? (
                                        <div className="items-center justify-center h-full gap-2 text-sm text-tertiary">
                                            <Spinner className="size-4" />
                                            Loading signals...
                                        </div>
                                    ) : selectedReportSignals && selectedReportSignals.length > 0 ? (
                                        <SignalGraphTab signals={selectedReportSignals} />
                                    ) : (
                                        <p className="text-sm text-tertiary m-0 p-6">No signals yet.</p>
                                    )}
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { isRunningSessionAnalysis } = useValues(inboxSceneLogic)
    const { runSessionAnalysis } = useActions(inboxSceneLogic)
    const { enabledSourcesCount } = useValues(signalSourcesLogic)
    const { openSourcesModal } = useActions(signalSourcesLogic)
    const { isDev } = useValues(preflightLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!isProductAutonomyEnabled) {
        return <NotFound object="page" caption="Check back later." />
    }

    return (
        <SceneContent className="gap-y-0 border-b-0">
            <SourcesModal />
            <SceneTitleSection
                name="Inbox"
                description={null}
                resourceType={{ type: 'inbox' }}
                actions={
                    <div className="flex items-center gap-2">
                        {isDev && (
                            <Tooltip title="Analyze the last 7 days of sessions">
                                <LemonButton
                                    type="secondary"
                                    onClick={() => runSessionAnalysis()}
                                    loading={isRunningSessionAnalysis}
                                    size="small"
                                    data-attr="run-session-analysis-button"
                                    tooltip="DEBUG-only"
                                    icon={<IconBug />}
                                >
                                    Run session analysis
                                </LemonButton>
                            </Tooltip>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconGear />}
                            onClick={openSourcesModal}
                            sideIcon={<LemonBadge.Number count={enabledSourcesCount} status="muted" size="small" />}
                        >
                            Edit sources
                        </LemonButton>
                    </div>
                }
            />

            <div className="flex items-start -mx-4 h-[calc(100vh-6.375rem+1px)]">
                <ReportListPane />
                <ReportDetailPane />
            </div>
        </SceneContent>
    )
}

export default InboxScene
