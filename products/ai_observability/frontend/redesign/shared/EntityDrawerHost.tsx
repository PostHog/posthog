import { useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { shouldCloseOnEscape } from '../trace/shouldCloseOnEscape'
import type { TraceDrawerListId } from '../trace/traceDrawerLists'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { DetailPanel, isDetailPanelFullWidth } from './components/DetailPanel'
import { EntityDrawerToolbar, EntityDrawerToolbarProps } from './components/EntityDrawerToolbar'

export interface EntityDrawerHostProps extends Omit<EntityDrawerToolbarProps, 'data-attr'> {
    /** The list whose trace drawer opens over this one. Escape closes that first. */
    traceListId: TraceDrawerListId
    children: ReactNode
    'data-attr': string
}

export function EntityDrawerHost({
    traceListId,
    children,
    'data-attr': dataAttr,
    ...toolbar
}: EntityDrawerHostProps): JSX.Element | null {
    const { mainContentRect } = useValues(panelLayoutLogic)
    const { openRef } = useValues(traceDrawerLogic({ listId: traceListId }))
    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'ai-observability-entity-drawer',
        placement: 'left',
        persistent: true,
        minSize: 420,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))
    const traceOpen = !!openRef
    const { onClose } = toolbar

    useEffect(() => {
        const closeOnEscape = (event: KeyboardEvent): void => {
            // The trace drawer stacks on top and closes on the same key, so this one waits for the next press.
            if (!traceOpen && shouldCloseOnEscape(event)) {
                onClose()
            }
        }
        document.addEventListener('keydown', closeOnEscape)
        return () => document.removeEventListener('keydown', closeOnEscape)
    }, [traceOpen, onClose])

    if (!mainContentRect) {
        return null
    }

    return (
        <DetailPanel
            aria-label={`${toolbar.noun} detail`}
            data-attr={dataAttr}
            rect={mainContentRect}
            width={desiredSize ?? Math.min(760, Math.round(mainContentRect.width / 2))}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={<EntityDrawerToolbar {...toolbar} data-attr={dataAttr} />}
        >
            {children}
        </DetailPanel>
    )
}
