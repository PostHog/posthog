import { useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useEffect, useRef } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DetailPanel, isDetailPanelFullWidth } from '../../redesign/shared/components/DetailPanel'
import { shouldCloseOnEscape } from '../../redesign/trace/shouldCloseOnEscape'
import { REPORT_RUN_PARAM } from '../evaluationReportDrawerLogic'

/** A side panel on the evaluations page, under the trace and report drawers it opens. */
export function EvaluationDetailDrawer({
    title,
    actions,
    onClose,
    children,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: {
    title: ReactNode
    actions?: ReactNode
    onClose: () => void
    children: ReactNode
    'aria-label': string
    'data-attr': string
}): JSX.Element | null {
    const { mainContentRect } = useValues(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'evaluation-detail-drawer',
        placement: 'left',
        persistent: true,
        minSize: 480,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    const onCloseRef = useRef(onClose)
    onCloseRef.current = onClose
    // Registered once on mount, so it runs before the listener of a trace or report drawer opened on top. That
    // drawer takes the first Escape, and this one closes on the next press.
    useEffect(() => {
        const closeOnEscape = (event: KeyboardEvent): void => {
            const { searchParams } = router.values
            if (shouldCloseOnEscape(event) && !searchParams.trace && !searchParams[REPORT_RUN_PARAM]) {
                onCloseRef.current()
            }
        }
        document.addEventListener('keydown', closeOnEscape)
        return () => document.removeEventListener('keydown', closeOnEscape)
    }, [])

    if (!mainContentRect) {
        return null
    }
    return (
        <DetailPanel
            aria-label={ariaLabel}
            data-attr={dataAttr}
            rect={mainContentRect}
            width={desiredSize ?? Math.min(960, Math.round((mainContentRect.width * 2) / 3))}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={
                <div className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="min-w-0 truncate font-semibold">{title}</span>
                    <div className="ml-auto flex shrink-0 items-center gap-1">
                        {actions}
                        <LemonButton
                            size="small"
                            icon={<IconX />}
                            tooltip={
                                <>
                                    Close <KeyboardShortcut escape />
                                </>
                            }
                            aria-label="Close"
                            onClick={onClose}
                            data-attr={`${dataAttr}-close`}
                        />
                    </div>
                </div>
            }
        >
            {children}
        </DetailPanel>
    )
}
