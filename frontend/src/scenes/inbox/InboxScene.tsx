import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconBug, IconGear, IconNotification, IconSearch, IconSparkles } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { GraphsHog, PopUpBinocularsHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SourcesModal } from './InboxSetup'
import { inboxSceneLogic } from './inboxSceneLogic'
import { SignalReport, SignalReportArtefact } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

function ReportListItem({ report }: { report: SignalReport }): JSX.Element {
    const { selectedReportId } = useValues(inboxSceneLogic)
    const { setSelectedReportId } = useActions(inboxSceneLogic)

    const isSelected = selectedReportId === report.id

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
            className={`w-full text-left px-3 py-2.5 flex items-start gap-2 cursor-pointer rounded border border-primary ${
                isSelected ? 'bg-surface-primary' : 'bg-surface-secondary hover:bg-surface-tertiary'
            }`}
        >
            <div className="flex-1 min-w-0">
                <h4 className="text-sm font-medium m-0 truncate flex-1">{report.title || 'Untitled report'}</h4>

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
                <div className="flex items-center gap-2 mt-1.5 text-xs text-tertiary  whitespace-nowrap">
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
                    <LemonTag size="small">Weight: {report.total_weight.toFixed(1)}</LemonTag>

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

function ReportListPane(): JSX.Element {
    const { filteredReports, reportsLoading, searchQuery, reports, selectedReportId, hasSessionAnalysisSource } =
        useValues(inboxSceneLogic)
    const { setSearchQuery, openSourcesModal } = useActions(inboxSceneLogic)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [isScrollable, setIsScrollable] = useState(false)
    filteredReports.length = 0
    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        const check = (): void => setIsScrollable(el.scrollHeight > el.clientHeight)
        check()
        const observer = new ResizeObserver(check)
        observer.observe(el)
        return () => observer.disconnect()
    }, [filteredReports.length])

    return (
        <div
            ref={scrollRef}
            className={clsx(
                `flex-shrink-0 h-full p-3 overflow-y-auto w-full`,
                `@3xl/main-content-container:w-120 @3xl/main-content-container:max-w-[50%] @3xl/main-content-container:border-r border-primary`,
                selectedReportId != null && 'hidden @3xl/main-content-container:block'
            )}
        >
            <LemonInput
                type="search"
                placeholder="Search reports..."
                prefix={<IconSearch />}
                className="sticky top-0 z-10 bg-primary/50 backdrop-blur-xl mb-2"
                value={searchQuery}
                onChange={setSearchQuery}
                size="small"
                fullWidth
                disabledReason={
                    reportsLoading && reports.length === 0
                        ? 'Loading reports...'
                        : reports.length === 0
                          ? 'No reports yet'
                          : null
                }
            />
            {!hasSessionAnalysisSource && filteredReports.length > 0 && (
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
                            <p className="text-sm text-secondary font-medium m-0">
                                {searchQuery ? 'No reports match your search.' : 'No reports yet.'}
                            </p>
                            {!hasSessionAnalysisSource && (
                                <LemonButton
                                    type="secondary"
                                    icon={<IconNotification />}
                                    onClick={openSourcesModal}
                                    size="small"
                                    className="mt-2"
                                >
                                    Enable your first source
                                </LemonButton>
                            )}
                        </div>
                    </div>
                ) : (
                    <>
                        {filteredReports.map((report: SignalReport) => (
                            <ReportListItem key={report.id} report={report} />
                        ))}
                        {isScrollable && filteredReports.length > 0 && (
                            <Tooltip title="You've reached the end, friend." delayMs={0} placement="right">
                                <PopUpBinocularsHog className="-mb-3 mt-1 w-24 self-center h-auto object-bottom" />
                            </Tooltip>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

function ArtefactCard({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const content = artefact.content
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="flex items-center gap-2 mb-1">
                <LemonTag size="small">{artefact.type}</LemonTag>
                <TZLabel time={artefact.created_at} />
                {artefact.type === 'video_segment' && content.session_id && (
                    <ViewRecordingButton
                        sessionId={content.session_id}
                        timestamp={content.start_time}
                        size="xsmall"
                        type="secondary"
                        label="Play"
                    />
                )}
            </div>
            {content.session_id && (
                <p className="text-sm text-secondary m-0 mt-1 truncate">
                    Session: <span className="font-mono text-xs">{content.session_id}</span>
                </p>
            )}
            {content.summary && <p className="text-sm text-secondary m-0 mt-1">{content.summary}</p>}
        </div>
    )
}

function ReportDetailPane(): JSX.Element {
    const { selectedReport, hasSessionAnalysisSource, artefacts, artefactsLoading } = useValues(inboxSceneLogic)
    const { openSourcesModal } = useActions(inboxSceneLogic)

    const baseClasses = 'flex-1 min-w-0 h-full self-start bg-surface-primary overflow-y-auto flex flex-col'

    if (!selectedReport) {
        return (
            <div
                className={`${baseClasses} items-center justify-center p-8 cursor-default hidden @3xl/main-content-container:flex`}
            >
                <GraphsHog className="w-36 mb-6" />
                <h3 className="text-xl font-bold mb-4 text-center">
                    Welcome to your Inbox
                    <sup>
                        <IconSparkles />
                    </sup>
                </h3>
                <div className="flex flex-col gap-2 text-xs text-secondary max-w-md leading-normal *:border *:border-dashed *:rounded *:p-2 *:text-secondary">
                    <div className="-ml-2 mr-2">
                        <strong>Inbox hands you ready-to-run fixes for real user problems.</strong>
                        <br />
                        Just execute the resulting prompt in your favorite coding agent. Each fix's report comes with
                        hard evidence and impact numbers.
                    </div>
                    <div className="-mr-2 ml-2">
                        <strong>Background analysis of your data - while you sleep.</strong>
                        <br />
                        Powerful new analysis of sessions watches every recording for you. Integrations with external
                        sources on the way: issue trackers, support platforms, and more.
                    </div>
                </div>
                {!hasSessionAnalysisSource && (
                    <LemonButton type="primary" onClick={openSourcesModal} icon={<IconNotification />} className="mt-4">
                        Enable your first source now
                    </LemonButton>
                )}
            </div>
        )
    }

    const reportArtefacts = artefacts[selectedReport.id]

    return (
        <div className={baseClasses} style={{ height: 'calc(100vh - 11rem)' }}>
            <div className="flex-1 overflow-y-auto py-8 px-6 mx-auto max-w-240">
                <Link
                    to={urls.inbox()}
                    className="inline-flex items-center gap-1 text-sm text-secondary mb-4 @3xl/main-content-container:hidden"
                >
                    <IconArrowLeft className="size-4" />
                    All reports
                </Link>
                <div className="mb-4">
                    <div className="flex items-center gap-2 mb-1">
                        <h2 className="text-lg font-semibold m-0 flex-1">
                            {selectedReport.title || 'Untitled report'}
                        </h2>
                        <LemonTag size="small">Weight: {selectedReport.total_weight.toFixed(1)}</LemonTag>
                    </div>
                    {selectedReport.summary && (
                        <p className="text-sm text-secondary m-0 mt-2">{selectedReport.summary}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-tertiary">
                        {selectedReport.relevant_user_count !== null && selectedReport.relevant_user_count > 0 && (
                            <span>
                                {selectedReport.relevant_user_count}{' '}
                                {selectedReport.relevant_user_count === 1 ? 'user' : 'users'}
                            </span>
                        )}
                        {selectedReport.signal_count > 0 && (
                            <span>
                                {selectedReport.signal_count} {selectedReport.signal_count === 1 ? 'signal' : 'signals'}
                            </span>
                        )}
                        <span>Created: {humanFriendlyDetailedTime(selectedReport.created_at)}</span>
                        <span>Updated: {humanFriendlyDetailedTime(selectedReport.updated_at)}</span>
                    </div>
                </div>

                <div>
                    <h4 className="text-xs font-semibold text-tertiary uppercase tracking-wide mb-2">Artefacts</h4>
                    {artefactsLoading && !reportArtefacts ? (
                        <div className="flex items-center gap-2 text-sm text-tertiary py-2">
                            <Spinner className="size-4" />
                            Loading artefacts...
                        </div>
                    ) : reportArtefacts && reportArtefacts.length > 0 ? (
                        <div className="space-y-2">
                            {reportArtefacts.map((artefact: SignalReportArtefact) => (
                                <ArtefactCard key={artefact.id} artefact={artefact} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-sm text-tertiary m-0">No artefacts yet.</p>
                    )}
                </div>
            </div>
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const { isRunningSessionAnalysis, enabledSourcesCount } = useValues(inboxSceneLogic)
    const { runSessionAnalysis, openSourcesModal } = useActions(inboxSceneLogic)
    const { isDev } = useValues(preflightLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!isProductAutonomyEnabled) {
        return <></>
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

            <div className="flex items-start -mx-4 h-[calc(100vh-6.375rem)]">
                <ReportListPane />
                <ReportDetailPane />
            </div>
        </SceneContent>
    )
}

export default InboxScene
