import { useActions, useValues } from 'kea'
import { EventType, SessionRecordingPlayerProps, SessionRecordingPlayerTab } from '~/types'
import { PlayerList } from 'scenes/session-recordings/player/list/PlayerList'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, interleave } from 'lib/utils'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import { EventDetails } from 'scenes/events'
import React from 'react'
import { LemonButton } from '@posthog/lemon-ui'
import { UnverifiedEvent, IconTerminal } from 'lib/components/icons'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

export function PlayerInspector({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { tab } = useValues(sharedListLogic({ sessionRecordingId, playerKey }))

    return (
        <PlayerList
            sessionRecordingId={sessionRecordingId}
            playerKey={playerKey}
            tab={tab}
            row={{
                status: (record) => {
                    if (record.level === 'match') {
                        return RowStatus.Match
                    }
                    if (tab === SessionRecordingPlayerTab.EVENTS) {
                        return null
                    }
                    // Below statuses only apply to console logs
                    if (record.level === 'warn') {
                        return RowStatus.Warning
                    }
                    if (record.level === 'log') {
                        return RowStatus.Information
                    }
                    if (record.level === 'error') {
                        return RowStatus.Error
                    }
                    if (record.level === 'error') {
                        return RowStatus.Error
                    }
                    return RowStatus.Information
                },
                content: function renderContent(record, _, expanded) {
                    if (tab === SessionRecordingPlayerTab.CONSOLE) {
                        return (
                            <div
                                className="font-mono text-xs w-full text-ellipsis leading-6"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={
                                    expanded
                                        ? {
                                              display: '-webkit-box',
                                              WebkitLineClamp: 6,
                                              WebkitBoxOrient: 'vertical',
                                              overflow: 'hidden',
                                              whiteSpace: 'normal',
                                          }
                                        : undefined
                                }
                            >
                                {interleave(record.previewContent, ' ')}
                            </div>
                        )
                    }

                    return (
                        <div className="flex flex-row justify-start whitespace-nowrap">
                            <PropertyKeyInfo
                                className="font-medium"
                                disableIcon
                                disablePopover
                                ellipsis={true}
                                value={capitalizeFirstLetter(autoCaptureEventToDescription(record as any))}
                            />
                            {record.event === '$autocapture' ? (
                                <span className="text-muted-alt ml-2">(Autocapture)</span>
                            ) : null}
                            {record.event === '$pageview' ? (
                                <span className="text-muted-alt ml-2">
                                    {record.properties.$pathname || record.properties.$current_url}
                                </span>
                            ) : null}
                        </div>
                    )
                },
                sideContent: function renderSideContent(record) {
                    if (tab === SessionRecordingPlayerTab.CONSOLE) {
                        return <div className="font-mono text-xs">{record.traceContent?.[0]}</div>
                    }
                    return null
                },
            }}
            expandable={{
                expandedRowRender: function renderExpand(record) {
                    if (!record) {
                        return null
                    }
                    if (tab === SessionRecordingPlayerTab.CONSOLE) {
                        return (
                            <div className="py-2 pr-2 pl-18 font-mono text-xs leading-6">
                                {record.fullContent?.map((content: JSX.Element, i: number) => (
                                    <React.Fragment key={i}>
                                        {content}
                                        <br />
                                    </React.Fragment>
                                ))}
                            </div>
                        )
                    }
                    return (
                        <EventDetails
                            event={record as EventType}
                            tableProps={{ size: 'xs', bordered: false, className: 'pt-1' }}
                        />
                    )
                },
            }}
        />
    )
}

export function PlayerInspectorPicker({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { tab } = useValues(sharedListLogic({ sessionRecordingId, playerKey }))
    const { setTab } = useActions(sharedListLogic({ sessionRecordingId, playerKey }))

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        200: 'normal',
    })

    return (
        <div ref={ref} className="flex flex-1 items-center gap-1">
            <LemonButton
                size="small"
                icon={<UnverifiedEvent />}
                status={tab === SessionRecordingPlayerTab.EVENTS ? 'primary' : 'primary-alt'}
                active={tab === SessionRecordingPlayerTab.EVENTS}
                onClick={() => setTab(SessionRecordingPlayerTab.EVENTS)}
            >
                {size === 'compact' ? '' : 'Events'}
            </LemonButton>
            <LemonButton
                size="small"
                icon={<IconTerminal />}
                status={tab === SessionRecordingPlayerTab.CONSOLE ? 'primary' : 'primary-alt'}
                active={tab === SessionRecordingPlayerTab.CONSOLE}
                onClick={() => {
                    setTab(SessionRecordingPlayerTab.CONSOLE)
                }}
            >
                {size === 'compact' ? '' : 'Console'}
            </LemonButton>
        </div>
    )
}
