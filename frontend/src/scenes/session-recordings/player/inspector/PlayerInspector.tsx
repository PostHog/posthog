import { useValues } from 'kea'
import { EventType, SessionRecordingPlayerTab } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, interleave } from 'lib/utils'
import { RowStatus } from 'scenes/session-recordings/player/inspector/v1/listLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { EventDetails } from 'scenes/events'
import React from 'react'
import { LemonDivider } from '@posthog/lemon-ui'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { PlayerInspectorList } from './v2/PlayerInspectorList'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerList } from './v1/PlayerList'
import { PlayerInspectorControls as PlayerInspectorControlsV1 } from './v1/PlayerInspectorControls'
import { PlayerInspectorControls as PlayerInspectorControlsV2 } from './v2/PlayerInspectorControls'

export function PlayerInspector(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { sessionRecordingId, playerKey } = props
    const { tab } = useValues(playerInspectorLogic(props))
    const { featureFlags } = useValues(featureFlagLogic)
    const inspectorV2 = !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_V2]

    return (
        <>
            {inspectorV2 ? <PlayerInspectorControlsV2 {...props} /> : <PlayerInspectorControlsV1 {...props} />}
            <LemonDivider className="my-0" />

            {inspectorV2 ? (
                <PlayerInspectorList {...props} />
            ) : (
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
            )}
        </>
    )
}
