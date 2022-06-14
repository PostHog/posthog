import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import './NetworkRequests.scss'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { SessionNetworkRequest } from '~/types'
import { LemonButton } from 'lib/components/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { colonDelimitedDuration, humanFriendlyNumber } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'

const HumanizeURL = ({ url }: { url: string | undefined }): JSX.Element => {
    if (!url) {
        return <span>(empty string)</span>
    }
    const parsedUrl = new URL(url)
    return (
        <span>
            <Tooltip
                title={
                    <>
                        <div>
                            {parsedUrl.protocol}&#47;&#47;
                            {parsedUrl.hostname}
                        </div>
                        <div>{parsedUrl.pathname}</div>
                        {parsedUrl.search && <div>{parsedUrl.search}</div>}
                    </>
                }
            >
                {parsedUrl.pathname}
            </Tooltip>
        </span>
    )
}

const friendlyMilliseconds = (duration: number | undefined): string => {
    const numberPart = duration ? humanFriendlyNumber(duration, 0) : 'unknown number of'
    return `${numberPart} milliseconds`
}

const Title = ({ networkRequest, title }: { networkRequest: SessionNetworkRequest; title: string }): JSX.Element => (
    <div className="Title">
        <h3>{title}</h3>{' '}
        <div className="NetworkRequestTime">
            {colonDelimitedDuration(Math.floor((networkRequest.playerPosition?.time ?? 0) / 1000))}
        </div>
    </div>
)

const NavigationRequestRow = ({ networkRequest }: { networkRequest: SessionNetworkRequest }): JSX.Element => (
    <>
        <Title networkRequest={networkRequest} title="Navigation" />
        <p>
            to <HumanizeURL url={networkRequest.url} /> took {friendlyMilliseconds(networkRequest.duration)}
        </p>
    </>
)

const PaintRequestRow = ({ networkRequest }: { networkRequest: SessionNetworkRequest }): JSX.Element => (
    <>
        <Title networkRequest={networkRequest} title="Browser Event" />
        <p>
            {networkRequest.eventName} occurred after {friendlyMilliseconds(networkRequest.timing)}
        </p>
    </>
)

const ResourceRequestRow = ({ networkRequest }: { networkRequest: SessionNetworkRequest }): JSX.Element => (
    <>
        <Title networkRequest={networkRequest} title="Network Request" />
        <p>
            to <HumanizeURL url={networkRequest.url} /> took {friendlyMilliseconds(networkRequest.duration)}
        </p>
    </>
)

const UnknownRequestTypeRow = ({ networkRequest }: { networkRequest: SessionNetworkRequest }): JSX.Element => (
    <>
        <Title networkRequest={networkRequest} title="Unknown request type" />
        <pre>{JSON.stringify(networkRequest)}</pre>
    </>
)

const NetworkRequestRow = (sessionNetworkRequest: SessionNetworkRequest): JSX.Element => {
    switch (sessionNetworkRequest.type) {
        case 'navigation':
            return <NavigationRequestRow networkRequest={sessionNetworkRequest} />
        case 'paint':
            return <PaintRequestRow networkRequest={sessionNetworkRequest} />
        case 'resource':
            return <ResourceRequestRow networkRequest={sessionNetworkRequest} />
        default:
            return <UnknownRequestTypeRow networkRequest={sessionNetworkRequest} />
    }
}

export function NetworkRequests(): JSX.Element | null {
    const { parsedNetworkRequests, sessionNetworkRequestsLoading } = useValues(sessionRecordingLogic)
    const { reportRecordingNetworkRequestFeedback } = useActions(eventUsageLogic)
    const { seek } = useActions(sessionRecordingPlayerLogic)
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)

    const renderSessionNetworkRequest = (sessionNetworkRequest: SessionNetworkRequest, index: number): JSX.Element => {
        return (
            <div
                className={`NetworkRequestRow Type__${sessionNetworkRequest.type}`}
                key={index}
                onClick={() => {
                    seek(sessionNetworkRequest.playerPosition)
                }}
            >
                <div className="NetworkRequestEntry">{NetworkRequestRow(sessionNetworkRequest)}</div>
            </div>
        )
    }

    return (
        <div className="SessionNetworkRequestsContainer">
            <div className="SessionNetworkRequestsList">
                {sessionNetworkRequestsLoading ? (
                    <div style={{ display: 'flex', height: '100%', justifyContent: 'center', alignItems: 'center' }}>
                        <Spinner size="lg" />
                    </div>
                ) : parsedNetworkRequests?.length || 0 > 0 ? (
                    <AutoSizer>
                        {({ height, width }: { height: number; width: number }) => (
                            <div style={{ height: height, width: width, overflowY: 'scroll', paddingBottom: 5 }}>
                                {parsedNetworkRequests?.map((networkRequest, index) =>
                                    renderSessionNetworkRequest(networkRequest, index)
                                )}
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
                        <h3 style={{ textAlign: 'center' }}>There are no network requests for this recording</h3>

                        <p className="text-muted" style={{ textAlign: 'center' }}>
                            For network requests to appear, the feature must first be enabled in <code>posthog-js</code>
                            .
                        </p>
                        {/*<LemonButton*/}
                        {/*    type="secondary"*/}
                        {/*    style={{ margin: '0 8px' }}*/}
                        {/*    href="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"*/}
                        {/*>*/}
                        {/*    Learn more*/}
                        {/*</LemonButton>*/}
                    </div>
                )}
            </div>
            <div className="FeedbackContainer">
                <p style={{ marginBottom: 8, textAlign: 'center' }}>
                    Are you finding the network requests feature useful?
                </p>
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
                                    reportRecordingNetworkRequestFeedback(
                                        parsedNetworkRequests?.length || 0,
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
