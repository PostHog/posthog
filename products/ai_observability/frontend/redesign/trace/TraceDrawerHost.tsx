import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DetailPanel, isDetailPanelFullWidth } from '../shared/components/DetailPanel'
import { TraceDrawerToolbar } from './components/TraceDrawerToolbar'
import { isOverlayOpen } from './shouldCloseOnEscape'
import { TRACE_DRAWER_LISTS, TraceDrawerListId } from './traceDrawerLists'
import { TraceStepDirection, traceDrawerLogic } from './traceDrawerLogic'
import { TraceViewHost } from './TraceViewHost'

export interface TraceDrawerHostProps {
    listId: TraceDrawerListId
}

export function TraceDrawerHost({ listId }: TraceDrawerHostProps): JSX.Element | null {
    const logic = traceDrawerLogic({ listId })
    const { hostId, openRef, position, previousTrace, nextTrace, fullPageHref } = useValues(logic)
    const { stepTo, close } = useActions(logic)
    const showNavigation = TRACE_DRAWER_LISTS[listId].showNavigation !== false
    const { mainContentRect } = useValues(panelLayoutLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'trace-drawer',
        placement: 'left',
        persistent: true,
        minSize: 480,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    // Stepping unmounts the trace view, and with it any modal opened from it, so a key never steps under an open overlay.
    const stepUnlessOverlayOpen = (direction: TraceStepDirection): void => {
        if (!isOverlayOpen()) {
            stepTo(direction)
        }
    }
    useShortcut({
        name: 'TraceDrawerPrevious',
        keybind: [['p']],
        intent: 'Previous trace',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('previous'),
        disabled: !previousTrace,
    })
    useShortcut({
        name: 'TraceDrawerNext',
        keybind: [['n']],
        intent: 'Next trace',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('next'),
        disabled: !nextTrace,
    })

    if (!openRef || !fullPageHref || !mainContentRect) {
        return null
    }

    return (
        <DetailPanel
            aria-label="Trace detail"
            data-attr="trace-drawer"
            rect={mainContentRect}
            width={desiredSize ?? Math.round((mainContentRect.width * 2) / 3)}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={
                <TraceDrawerToolbar
                    showNavigation={showNavigation}
                    position={position}
                    onPrevious={previousTrace ? () => stepTo('previous') : null}
                    onNext={nextTrace ? () => stepTo('next') : null}
                    fullPageHref={fullPageHref}
                    fullPageInNewTab={TRACE_DRAWER_LISTS[listId].fullPageInNewTab}
                    onClose={close}
                />
            }
        >
            <TraceViewHost
                key={openRef.traceId}
                hostId={hostId}
                traceId={openRef.traceId}
                timestampHint={openRef.timestamp}
                backLink={null}
            />
        </DetailPanel>
    )
}
