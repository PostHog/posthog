import { LemonBanner } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'

import { errorPropertiesLogic } from './errorPropertiesLogic'
import { ChainedStackTraces } from './StackTraces'
import { ErrorEventId, ErrorEventProperties } from './types'
import { concatValues } from './utils'

export function ErrorDisplay({
    eventProperties,
    eventId,
}: {
    eventProperties: ErrorEventProperties
    eventId: ErrorEventId
}): JSX.Element {
    return (
        <BindLogic logic={errorPropertiesLogic} props={{ properties: eventProperties, id: eventId }}>
            <ErrorDisplayContent />
        </BindLogic>
    )
}

export function ErrorDisplayContent(): JSX.Element {
    const { exceptionAttributes, hasStacktrace } = useValues(errorPropertiesLogic)
    const { type, value, sentryUrl, level, ingestionErrors, handled } = exceptionAttributes || {}
    return (
        <div className="flex flex-col deprecated-space-y-2 pb-2">
            <h1 className="mb-0">{type || level}</h1>
            {!hasStacktrace && <div className="text-secondary italic">{value}</div>}
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
                <TitledSnack title="handled" value={String(handled)} />
                <TitledSnack
                    title="library"
                    value={concatValues(exceptionAttributes, 'lib', 'libVersion') ?? 'unknown'}
                />
                <TitledSnack
                    title="browser"
                    value={concatValues(exceptionAttributes, 'browser', 'browserVersion') ?? 'unknown'}
                />
                <TitledSnack title="os" value={concatValues(exceptionAttributes, 'os', 'osVersion') ?? 'unknown'} />
            </div>

            {ingestionErrors || hasStacktrace ? <LemonDivider dashed={true} /> : null}
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
            {hasStacktrace && <StackTrace />}
        </div>
    )
}

const StackTrace = (): JSX.Element => {
    const [showAllFrames, setShowAllFrames] = useState(false)
    return (
        <>
            <div className="flex gap-1 mt-6 justify-between items-center">
                <h3 className="mb-0">Stack Trace</h3>
                <LemonSwitch
                    checked={showAllFrames}
                    label="Show entire stack trace"
                    onChange={() => setShowAllFrames(!showAllFrames)}
                />
            </div>
            <ChainedStackTraces showAllFrames={showAllFrames} />
        </>
    )
}
