import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DetailPanel, isDetailPanelFullWidth } from '../../redesign/shared/components/DetailPanel'
import { isOverlayOpen } from '../../redesign/trace/shouldCloseOnEscape'
import { ReportStepDirection, evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { EvaluationReportDrawerToolbar } from './EvaluationReportDrawerToolbar'
import { EvaluationReportViewer } from './EvaluationReportViewer'

export interface EvaluationReportDrawerProps {
    evaluationId: string
    /** Why "Generate a new report" is off, such as missing edit access or a missing passing rule. */
    generateDisabledReason?: string
    onOpenTrace: (traceId: string, eventId: string | null) => void
    onShowResults: (periodStart: string, periodEnd: string) => void
}

export function EvaluationReportDrawer({
    evaluationId,
    generateDisabledReason,
    onOpenTrace,
    onShowResults,
}: EvaluationReportDrawerProps): JSX.Element | null {
    const logic = evaluationReportDrawerLogic({ evaluationId })
    const { openRunId, openRun, isSearchingForRun, position, previousRun, nextRun, reportRuns } = useValues(logic)
    const { stepTo, close, openRun: openRunById } = useActions(logic)
    const { activeReport, generateResultLoading, waitingForNewReportSince } = useValues(
        evaluationReportLogic({ evaluationId })
    )
    const { generateReport } = useActions(evaluationReportLogic({ evaluationId }))
    const { mainContentRect } = useValues(panelLayoutLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'evaluation-report-drawer',
        placement: 'left',
        persistent: true,
        minSize: 480,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    const stepUnlessOverlayOpen = (direction: ReportStepDirection): void => {
        if (!isOverlayOpen()) {
            stepTo(direction)
        }
    }
    useShortcut({
        name: 'EvaluationReportDrawerPrevious',
        keybind: [['p']],
        intent: 'Newer report',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('previous'),
        disabled: !openRunId || !previousRun,
    })
    useShortcut({
        name: 'EvaluationReportDrawerNext',
        keybind: [['n']],
        intent: 'Older report',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('next'),
        disabled: !openRunId || !nextRun,
    })

    if (!openRunId || !mainContentRect) {
        return null
    }

    const isWriting = generateResultLoading || !!waitingForNewReportSince
    const newestRun = reportRuns[0]

    return (
        <DetailPanel
            aria-label="Evaluation report"
            data-attr="llma-evaluation-report-drawer"
            rect={mainContentRect}
            width={desiredSize ?? Math.round((mainContentRect.width * 2) / 3)}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={
                <EvaluationReportDrawerToolbar
                    position={position}
                    onPrevious={previousRun ? () => stepTo('previous') : null}
                    onNext={nextRun ? () => stepTo('next') : null}
                    onCopyLink={() => void copyToClipboard(window.location.href, 'link to this report')}
                    onGenerate={activeReport && !isWriting ? () => generateReport(activeReport.id) : null}
                    generateDisabledReason={
                        generateDisabledReason ?? (isWriting ? 'A new report is being written' : undefined)
                    }
                    onClose={close}
                />
            }
        >
            {openRun ? (
                <EvaluationReportViewer
                    key={openRun.id}
                    reportRun={openRun}
                    onOpenTrace={onOpenTrace}
                    onShowResults={() => onShowResults(openRun.period_start, openRun.period_end)}
                />
            ) : isSearchingForRun ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-6 w-2/3" />
                    <LemonSkeleton className="h-4 w-1/3" />
                    <LemonSkeleton className="h-32 w-full" />
                </div>
            ) : (
                <div className="flex flex-col items-start gap-2 text-sm">
                    <p className="mb-0">This report no longer exists.</p>
                    {newestRun && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => openRunById(newestRun.id, 'link')}
                            data-attr="llma-evaluation-report-drawer-open-latest"
                        >
                            Open the latest report
                        </LemonButton>
                    )}
                </div>
            )}
        </DetailPanel>
    )
}
