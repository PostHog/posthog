import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { KnownException } from '../Exception/known-exceptions'
import { ErrorTrackingException } from '../types'

export function EmptyStackTrace({
    exception,
    knownException,
}: {
    exception: ErrorTrackingException
    knownException?: KnownException
}): JSX.Element {
    if (knownException) {
        return knownException.render(exception)
    }

    return (
        <div className="border-1 rounded">
            <div className="empty-message">
                <div className="flex flex-col h-full items-center justify-center m-5 text-center gap-3">
                    <h3 className="title">No stacktrace available</h3>
                    <p className="text-secondary description max-w-xl">
                        Resolved stack frames require uploaded source maps. If your code is minified, make sure you have
                        uploaded source maps for the relevant release — otherwise PostHog can&apos;t demangle frames.{' '}
                        <Link to="https://posthog.com/docs/error-tracking/installation" target="_blank">
                            Check the SDK setup
                        </Link>{' '}
                        or contact support if the problem persists.
                    </p>
                    <div className="flex flex-wrap gap-2 justify-center">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={`${urls.errorTrackingConfiguration()}#selectedSetting=error-tracking-symbol-sets`}
                        >
                            View symbol sets
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            size="small"
                            to="https://posthog.com/docs/error-tracking/upload-source-maps"
                            targetBlank
                        >
                            Source map docs
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}
