import './PlayerConsole.scss'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { RecordingConsoleLog } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'

export function PlayerConsole(): JSX.Element | null {
    const { orderedConsoleLogs, areAllSnapshotsLoaded } = useValues(sessionRecordingLogic)
    const { reportRecordingConsoleFeedback } = useActions(eventUsageLogic)
    const { seek } = useActions(sessionRecordingPlayerLogic)
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)

    const renderLogLine = (log: RecordingConsoleLog, index: number): JSX.Element => {
        return (
            <div
                className={`log-line level-${log.level}`}
                key={index}
                onClick={() => {
                    seek(log.playerPosition)
                }}
            >
                <div className="trace-string">
                    {log.parsedTraceURL ? (
                        `<a className="text-muted" href={log.parsedTraceURL} target="_blank">
                            {log.parsedTraceString}
                        </a>`
                    ) : (
                        <span className="text-muted">{log.parsedTraceString}</span>
                    )}
                </div>
                <p className="log-text">{log.parsedPayload}</p>
            </div>
        )
    }

    return (
        <div className="console-log-container">
            <div className="console-log">
                {areAllSnapshotsLoaded ? (
                    orderedConsoleLogs.length > 0 ? (
                        <AutoSizer>
                            {({ height, width }: { height: number; width: number }) => (
                                <div style={{ height: height, width: width, overflowY: 'scroll', paddingBottom: 5 }}>
                                    {/* Only display the first 150 logs because the list ins't virtualized */}
                                    {orderedConsoleLogs.slice(0, 150).map((log, index) => renderLogLine(log, index))}
                                    <div>
                                        {orderedConsoleLogs.length > 150 && (
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
                                style={{ margin: '0 8px' }}
                                href="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                            >
                                Learn more
                            </LemonButton>
                        </div>
                    )
                ) : (
                    <div style={{ display: 'flex', height: '100%', justifyContent: 'center', alignItems: 'center' }}>
                        <Spinner size="lg" />
                    </div>
                )}
            </div>
            <div className="console-feedback-container">
                <p style={{ marginBottom: 8, textAlign: 'center' }}>Are you finding the console log feature useful?</p>
                {feedbackSubmitted ? (
                    <p className="text-muted" style={{ marginBottom: 8, textAlign: 'center' }}>
                        Thanks for the input!
                    </p>
                ) : (
                    <div style={{ display: 'flex', width: '100%', justifyContent: 'center' }}>
                        {(
                            [
                                ['Yes', '👍 Yes!'],
                                ['No', '👎 Not really'],
                            ] as const
                        ).map((content, index) => (
                            <LemonButton
                                type="secondary"
                                key={index}
                                style={{ margin: '0 8px' }}
                                onClick={() => {
                                    setFeedbackSubmitted(true)
                                    reportRecordingConsoleFeedback(
                                        orderedConsoleLogs.length,
                                        content[0],
                                        'Are you finding the console log feature useful?'
                                    )
                                }}
                            >
                                {content[1]}
                            </LemonButton>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
