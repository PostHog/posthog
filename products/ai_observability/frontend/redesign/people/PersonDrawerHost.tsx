import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/lemon-ui/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/lemon-ui/Resizer/resizerLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DetailPanel, isDetailPanelFullWidth } from '../shared/components/DetailPanel'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { PersonDrawer } from './components/PersonDrawer'
import { PersonDrawerToolbar } from './components/PersonDrawerToolbar'
import { PERSON_TRACES_LIST, personDrawerLogic } from './personDrawerLogic'

export interface PersonDrawerHostProps {
    personId: string
}

/** The open person's drawer. A recent trace opens in its place, with a way back to the person. */
export function PersonDrawerHost({ personId }: PersonDrawerHostProps): JSX.Element | null {
    const logic = personDrawerLogic({ personId })
    const {
        person,
        status,
        firstSeen,
        recentTraces,
        traceTitles,
        recentSessions,
        sessionTitles,
        traceRows,
        sessionHref,
        viewAllHref,
        personHref,
        openTraceId,
    } = useValues(logic)
    const { loadPerson, loadRecentTraces, loadRecentSessions, close } = useActions(logic)
    const { openRow, close: closeTrace } = useActions(traceDrawerLogic({ listId: PERSON_TRACES_LIST }))
    const { mainContentRect } = useValues(panelLayoutLogic)

    const containerRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        containerRef,
        logicKey: 'person-drawer',
        placement: 'left',
        persistent: true,
        minSize: 480,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    const onOpenTrace = (traceId: string): void => {
        const row = traceRows.find((candidate) => candidate.traceId === traceId)
        if (row) {
            openRow(row)
        }
    }

    const panel = openTraceId ? (
        <TraceDrawerHost
            listId={PERSON_TRACES_LIST}
            back={{ label: person?.person.label ?? 'Back to person', onBack: closeTrace }}
        />
    ) : mainContentRect ? (
        <DetailPanel
            aria-label="Person detail"
            data-attr="ai-observability-person-drawer"
            rect={mainContentRect}
            width={desiredSize ?? Math.round((mainContentRect.width * 2) / 3)}
            containerRef={containerRef}
            resizer={isDetailPanelFullWidth(mainContentRect.width) ? null : <Resizer {...resizerProps} />}
            toolbar={<PersonDrawerToolbar onClose={close} />}
        >
            <PersonDrawer
                person={person}
                status={status}
                firstSeen={firstSeen}
                recentTraces={recentTraces}
                traceTitles={traceTitles}
                recentSessions={recentSessions}
                sessionTitles={sessionTitles}
                onOpenTrace={onOpenTrace}
                sessionHref={sessionHref}
                viewAllHref={viewAllHref}
                personHref={personHref}
                onRetryPerson={loadPerson}
                onRetryTraces={loadRecentTraces}
                onRetrySessions={loadRecentSessions}
            />
        </DetailPanel>
    ) : null

    return (
        <>
            <TraceDrawerRowsSync listId={PERSON_TRACES_LIST} rows={traceRows} />
            {panel}
        </>
    )
}
