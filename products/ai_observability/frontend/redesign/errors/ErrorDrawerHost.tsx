import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'
import { teamLogic } from 'scenes/teamLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import type { TraceListItemApi } from '../../generated/api.schemas'
import { isDetailPanelFullWidth } from '../shared/components/DetailPanel'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { TraceDrawerListId } from '../trace/traceDrawerLists'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { ErrorDrawerBody } from './components/ErrorDrawerBody'
import { errorDrawerLogic } from './errorDrawerLogic'

const LIST_ID: TraceDrawerListId = 'error-traces'

export function ErrorDrawerHost(): JSX.Element {
    const { openKey, openMessage, item, isNew, detailLoad, recentTracesLoad, recentTraceRows, previews, viewAllHref } =
        useValues(errorDrawerLogic)
    const { close, retry } = useActions(errorDrawerLogic)
    const { openTraceId } = useValues(traceDrawerLogic({ listId: LIST_ID }))
    const { openRow, close: closeTrace } = useActions(traceDrawerLogic({ listId: LIST_ID }))
    const { timezone } = useValues(teamLogic)
    const { mainContentRect } = useValues(panelLayoutLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'error-drawer',
        placement: 'left',
        persistent: true,
        minSize: 400,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    const openTrace = (trace: TraceListItemApi): void => {
        const row = recentTraceRows.find(({ traceId }) => traceId === trace.id)
        if (row) {
            openRow(row)
        }
    }

    return (
        <>
            <TraceDrawerRowsSync listId={LIST_ID} rows={recentTraceRows} />
            <TraceDrawerHost
                listId={LIST_ID}
                back={openMessage ? { label: openMessage, onBack: closeTrace } : undefined}
            />
            {/* An open trace takes the drawer's place, and closing it shows the error again. */}
            {openKey && !openTraceId && mainContentRect ? (
                <ErrorDrawerBody
                    rect={mainContentRect}
                    width={desiredSize ?? Math.round(mainContentRect.width / 2)}
                    containerRef={containerRef}
                    resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
                    onClose={close}
                    message={openMessage}
                    item={item}
                    isNew={isNew}
                    detail={detailLoad}
                    recentTraces={recentTracesLoad}
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
