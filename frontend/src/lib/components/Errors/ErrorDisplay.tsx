import { LemonBanner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { getExceptionAttributes, hasAnyInAppFrames, hasStacktrace } from 'scenes/error-tracking/utils'

import { EventType } from '~/types'

import { stackFrameLogic } from './stackFrameLogic'
import { ChainedStackTraces } from './StackTraces'
import { ErrorTrackingException } from './types'

export function ErrorDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { type, value, library, browser, os, sentryUrl, exceptionList, level, ingestionErrors, unhandled } =
        getExceptionAttributes(eventProperties)

    const exceptionWithStack = hasStacktrace(exceptionList)
    const fingerprintRecord: FingerprintRecordPart[] = eventProperties.$exception_fingerprint_record || []
    const hasFingerprintRecord = fingerprintRecord.length > 0

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
                <TitledSnack title="library" value={library} />
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
            {exceptionWithStack && <StackTrace exceptionList={exceptionList} />}
            {hasFingerprintRecord && <FingerprintComponents components={fingerprintRecord} />}
        </div>
    )
}

interface FingerprintRecordPart {
    type: 'frame' | 'content'
    raw_id?: string
    pieces?: string[]
    name?: string
}
const FingerprintComponents = ({ components }: { components: FingerprintRecordPart[] }): JSX.Element => {
    const { highlightFrame } = useActions(stackFrameLogic)
    const { highlightedFrameId } = useValues(stackFrameLogic)

    return (
        <div className="flex mb-4 items-center gap-2">
            <span className="font-semibold">Fingerprinted by:</span>
            <div className="flex flex-wrap gap-1">
                {components.map((component, index) => {
                    if (component.type === 'frame') {
                        return (
                            <span
                                key={index}
                                className={`px-2 py-1 rounded text-sm cursor-pointer transition-colors ${
                                    highlightedFrameId === component.raw_id ? 'bg-primary-highlight' : 'bg-bg-light'
                                }`}
                                onMouseEnter={() => highlightFrame(component.raw_id ? component.raw_id : null)}
                                onMouseLeave={() => highlightFrame(null)}
                            >
                                Stack frame
                            </span>
                        )
                    } else if (component.type === 'content') {
                        return (
                            <span key={index} className="px-2 py-1 bg-bg-light rounded text-sm">
                                {component.name}
                            </span>
                        )
                    }
                    return null
                })}
            </div>
        </div>
    )
}

const StackTrace = ({ exceptionList }: { exceptionList: ErrorTrackingException[] }): JSX.Element => {
    const { showAllFrames } = useValues(stackFrameLogic)
    const { setShowAllFrames } = useActions(stackFrameLogic)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return (
        <>
            <div className="flex gap-1 mt-6 justify-between items-center">
                <h3 className="mb-0">Stack Trace</h3>
                {hasAnyInApp ? (
                    <LemonSwitch
                        checked={showAllFrames}
                        label="Show entire stack trace"
                        onChange={() => setShowAllFrames(!showAllFrames)}
                    />
                ) : null}
            </div>
            <ChainedStackTraces exceptionList={exceptionList} showAllFrames={hasAnyInApp ? showAllFrames : true} />
        </>
    )
}
