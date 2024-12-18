import { LemonBanner } from '@posthog/lemon-ui'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { getExceptionAttributes, hasAnyInAppFrames, hasStacktrace } from 'scenes/error-tracking/utils'

import { EventType } from '~/types'

import { ChainedStackTraces } from './StackTraces'
import { ErrorTrackingException } from './types'

export function ErrorDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { type, value, synthetic, library, browser, os, sentryUrl, exceptionList, level, ingestionErrors } =
        getExceptionAttributes(eventProperties)

    const exceptionWithStack = hasStacktrace(exceptionList)

    return (
        <div className="flex flex-col space-y-2 pb-2">
            <h1 className="mb-0">{type || level}</h1>
            <div className="flex flex-row gap-2 flex-wrap">
                <LemonTag type="danger">{value}</LemonTag>
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
                <TitledSnack title="synthetic" value={synthetic ?? false} />
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
        </div>
    )
}

const StackTrace = ({ exceptionList }: { exceptionList: ErrorTrackingException[] }): JSX.Element => {
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)
    const [showAllFrames, setShowAllFrames] = useState(!hasAnyInApp)

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
            <ChainedStackTraces exceptionList={exceptionList} showAllFrames />
        </>
    )
}
