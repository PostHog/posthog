import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'
import { teamLogic } from 'scenes/teamLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import type { TraceListItemApi } from '../../generated/api.schemas'
import { traceRowOf } from '../diagnostics/diagnosticsDrawerReads'
import { isDetailPanelFullWidth } from '../shared/components/DetailPanel'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { TraceDrawerListId } from '../trace/traceDrawerLists'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { ToolDrawerBody } from './components/ToolDrawerBody'
import { ToolTraceSection, toolDrawerLogic } from './toolDrawerLogic'

const LIST_ID: TraceDrawerListId = 'tool-traces'

export function ToolDrawerHost(): JSX.Element {
    const {
        openKey,
        openName,
        item,
        detailLoad,
        showsFailures,
        recentFailuresLoad,
        recentCallsLoad,
        traceRows,
        previews,
        viewAllHref,
    } = useValues(toolDrawerLogic)
    const { close, retry, setTraceSection } = useActions(toolDrawerLogic)
    const { openTraceId } = useValues(traceDrawerLogic({ listId: LIST_ID }))
    const { openRow, close: closeTrace } = useActions(traceDrawerLogic({ listId: LIST_ID }))
    const { timezone } = useValues(teamLogic)
    const { mainContentRect } = useValues(panelLayoutLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'tool-drawer',
        placement: 'left',
        persistent: true,
        minSize: 400,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    // The trace drawer steps through the section the trace opened from, which the rows sync hands it.
    const openTrace = (section: ToolTraceSection, trace: TraceListItemApi): void => {
        setTraceSection(section)
        openRow(traceRowOf(trace))
    }

    return (
        <>
            <TraceDrawerRowsSync listId={LIST_ID} rows={traceRows} />
            <TraceDrawerHost listId={LIST_ID} back={openName ? { label: openName, onBack: closeTrace } : undefined} />
            {/* An open trace takes the drawer's place, and closing it shows the tool again. */}
            {openKey && !openTraceId && mainContentRect ? (
                <ToolDrawerBody
                    rect={mainContentRect}
                    width={desiredSize ?? Math.round(mainContentRect.width / 2)}
                    containerRef={containerRef}
                    resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
                    onClose={close}
                    name={openName}
                    item={item}
                    detail={detailLoad}
                    showsFailures={showsFailures}
                    recentFailures={recentFailuresLoad}
                    recentCalls={recentCallsLoad}
                    previews={previews}
                    timezone={timezone}
                    viewAllHref={viewAllHref}
                    onRetry={retry}
                    onOpenTrace={openTrace}
                />
            ) : null}
        </>
    )
}
