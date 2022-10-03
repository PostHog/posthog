import './PlayerConsole.scss'
import { useActions, useValues } from 'kea'
import React from 'react'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { RecordingConsoleLog, SessionRecordingPlayerProps } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { consoleLogsListLogic, FEEDBACK_OPTIONS } from 'scenes/session-recordings/player/list/consoleLogsListLogic'

export function PlayerConsole({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element | null {
    const { feedbackSubmitted, consoleListData } = useValues(consoleLogsListLogic({ sessionRecordingId, playerKey }))
    const { submitFeedback } = useActions(consoleLogsListLogic({ sessionRecordingId, playerKey }))
    const { sessionPlayerDataLoading } = useValues(sessionRecordingDataLogic({ sessionRecordingId }))
    const { seek } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))

    const renderLogLine = (log: RecordingConsoleLog, index: number): JSX.Element => {
        return (
            <div
                className={`log-line level-${log.level}`}
                key={index}
                onClick={() => {
                    seek(log.playerPosition)
                }}
            >
                <div className="trace-string">{log.traceContent?.[0]}</div>
                <p className="log-text">{log.parsedPayload}</p>
            </div>
        )
    }

    return (
        <div className="console-log-container">
            <div className="console-log">
                {sessionPlayerDataLoading ? (
                    <div style={{ display: 'flex', height: '100%', justifyContent: 'center', alignItems: 'center' }}>
                        <Spinner className="text-4xl" />
                    </div>
                ) : consoleListData.length > 0 ? (
                    <AutoSizer>
                        {({ height, width }: { height: number; width: number }) => (
                            <div style={{ height: height, width: width, overflowY: 'scroll', paddingBottom: 5 }}>
                                {/* Only display the first 150 logs because the list ins't virtualized */}
                                {consoleListData.slice(0, 150).map((log, index) => renderLogLine(log, index))}
                                <div>
                                    {consoleListData.length > 150 && (
                                        <div className="more-logs-available">
                                            While console logs are in beta, only 150 logs are displayed.
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </AutoSizer>
                ) : (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            height: '100%',
                            justifyContent: 'center',
                            alignItems: 'center',
                            margin: 20,
                        }}
                    >
                        <h3 style={{ textAlign: 'center' }}>There are no console logs for this recording</h3>

                        <p className="text-muted" style={{ textAlign: 'center' }}>
                            For logs to appear, the feature must first be enabled in <code>posthog-js</code>.
                        </p>
                        <LemonButton
                            type="secondary"
                            className="my-2"
                            to="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                        >
                            Learn more
                        </LemonButton>
                    </div>
                )}
            </div>
            <div className="console-feedback-container">
                <p className="mb-2 text-center">Are you finding the console log feature useful?</p>
                {feedbackSubmitted ? (
                    <p className="text-muted mb-2 text-center">Thanks for the input!</p>
                ) : (
                    <div className="flex justify-center gap-2">
                        {Object.values(FEEDBACK_OPTIONS).map(({ label, value }, index) => (
                            <LemonButton
                                type="secondary"
                                key={index}
                                onClick={() => {
                                    submitFeedback(value)
                                }}
                            >
                                {label}
                            </LemonButton>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
