import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DetailPanel, isDetailPanelFullWidth } from '../shared/components/DetailPanel'
import { TraceViewContainer } from './adapter/TraceViewContainer'
import { TraceDrawerToolbar } from './components/TraceDrawerToolbar'
import { traceDrawerLogic } from './traceDrawerLogic'

export interface TraceDrawerHostProps {
    listId: string
}

export function TraceDrawerHost({ listId }: TraceDrawerHostProps): JSX.Element | null {
    const logic = traceDrawerLogic({ listId })
    const { hostId, isEnabled, openRef, position, previousTrace, nextTrace, fullPageHref } = useValues(logic)
    const { stepTo, close } = useActions(logic)
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

    if (!isEnabled || !openRef || !fullPageHref || !mainContentRect) {
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
                    position={position}
                    onPrevious={previousTrace ? () => stepTo('previous') : null}
                    onNext={nextTrace ? () => stepTo('next') : null}
                    fullPageHref={fullPageHref}
                    onClose={close}
                />
            }
        >
            <TraceViewContainer
                key={openRef.traceId}
                hostId={hostId}
                traceId={openRef.traceId}
                timestampHint={openRef.timestamp}
                backLink={null}
            />
        </DetailPanel>
    )
}
