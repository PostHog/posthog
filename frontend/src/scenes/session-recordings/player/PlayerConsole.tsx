import './PlayerConsole.scss'
import { useActions, useValues } from 'kea'
import React from 'react'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { RecordingConsoleLog } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { consoleLogsListLogic, FEEDBACK_OPTIONS } from 'scenes/session-recordings/player/consoleLogsListLogic'

export function PlayerConsole(): JSX.Element | null {
    const { feedbackSubmitted, consoleLogs } = useValues(consoleLogsListLogic)
    const { submitFeedback } = useActions(consoleLogsListLogic)
    const { sessionPlayerDataLoading } = useValues(sessionRecordingLogic)
    const { seek } = useActions(sessionRecordingPlayerLogic)

    console.log('Console logs', consoleLogs)

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
                        <a className="text-muted" href={log.parsedTraceURL} target="_blank">
                            {log.parsedTraceString}
                        </a>
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
                {sessionPlayerDataLoading ? (
                    <div style={{ display: 'flex', height: '100%', justifyContent: 'center', alignItems: 'center' }}>
                        <Spinner size="lg" />
                    </div>
                ) : consoleLogs.length > 0 ? (
                    <AutoSizer>
                        {({ height, width }: { height: number; width: number }) => (
                            <div style={{ height: height, width: width, overflowY: 'scroll', paddingBottom: 5 }}>
                                {/* Only display the first 150 logs because the list ins't virtualized */}
                                {consoleLogs.slice(0, 150).map((log, index) => renderLogLine(log, index))}
                                <div>
                                    {consoleLogs.length > 150 && (
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
                        {Object.values(FEEDBACK_OPTIONS).map(({ label, value }, index) => (
                            <LemonButton
                                type="secondary"
                                key={index}
                                style={{ margin: '0 8px' }}
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
