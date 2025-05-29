import { LemonBanner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'

import { EventType } from '~/types'

import { FingerprintRecordPart, stackFrameLogic } from './stackFrameLogic'
import { ChainedStackTraces } from './StackTraces'
import { ErrorTrackingException } from './types'
import { hasInAppFrames, hasStacktrace } from './utils'

export function ErrorDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { type, value, library, browser, os, sentryUrl, exceptionList, level, ingestionErrors, unhandled } =
        getExceptionAttributes(eventProperties)

    const exceptionWithStack = hasStacktrace(exceptionList)
    const fingerprintRecords: FingerprintRecordPart[] = eventProperties.$exception_fingerprint_record || []

    return (
        <div className="flex flex-col deprecated-space-y-2 pb-2">
            <h1 className="mb-0">{type || level}</h1>
            {!exceptionWithStack && <div className="text-secondary italic">{value}</div>}
            <div className="flex flex-row gap-2 flex-wrap">
                <TitledSnack
                    type="success"
                    title="captured by"
                    value={
                        sentryUrl ? (
                            <Link
                                className="text-3000 hover:underline decoration-primary-alt cursor-pointer"
                                to={sentryUrl}
                                target="_blank"
                            >
                                Sentry
                            </Link>
                        ) : (
                            'PostHog'
                        )
                    }
                />
                <TitledSnack title="unhandled" value={String(unhandled)} />
                <TitledSnack title="library" value={library ?? 'unknown'} />
                <TitledSnack title="browser" value={browser ?? 'unknown'} />
                <TitledSnack title="os" value={os ?? 'unknown'} />
            </div>

            {ingestionErrors || exceptionWithStack ? <LemonDivider dashed={true} /> : null}
            {ingestionErrors && (
                <>
                    <LemonBanner type="error">
                        <ul>
                            {ingestionErrors.map((e, i) => (
                                <li key={i}>{e}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                </>
            )}
            {exceptionWithStack && <StackTrace exceptionList={exceptionList} fingerprintRecords={fingerprintRecords} />}
        </div>
    )
}

const StackTrace = ({
    exceptionList,
    fingerprintRecords,
}: {
    exceptionList: ErrorTrackingException[]
    fingerprintRecords: FingerprintRecordPart[]
}): JSX.Element => {
    const { showAllFrames } = useValues(stackFrameLogic)
    const { setShowAllFrames } = useActions(stackFrameLogic)
    const hasInApp = hasInAppFrames(exceptionList)

    return (
        <>
            <div className="flex gap-1 mt-6 justify-between items-center">
                <h3 className="mb-0">Stack Trace</h3>
                {hasInApp ? (
                    <LemonSwitch
                        checked={showAllFrames}
                        label="Show entire stack trace"
                        onChange={() => setShowAllFrames(!showAllFrames)}
                    />
                ) : null}
            </div>
            <ChainedStackTraces
                exceptionList={exceptionList}
                showAllFrames={hasInApp && showAllFrames}
                fingerprintRecords={fingerprintRecords}
            />
        </>
    )
}
