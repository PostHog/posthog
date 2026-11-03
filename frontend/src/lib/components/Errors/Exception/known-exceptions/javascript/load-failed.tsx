import { Link } from '@posthog/lemon-ui'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

const FETCH_FAILURE_MESSAGES = new Set(['Failed to fetch', 'Load failed'])

defineKnownException({
    match(exception) {
        return exception.type === 'TypeError' && FETCH_FAILURE_MESSAGES.has(exception.value)
    },
    render(exception) {
        return (
            <KnownExceptionBanner>
                <strong>{exception.value}</strong> is a message browsers emit when a <code>fetch()</code> call cannot
                complete. Because it is thrown from native code, no JavaScript stack trace is captured. Common causes
                are network errors, CORS misconfiguration, the request being aborted, or a browser extension blocking
                the request.{' '}
                <Link to="https://posthog.com/docs/error-tracking/common-questions" target="_blank">
                    Read our docs
                </Link>{' '}
                to learn how to add context to these errors.
            </KnownExceptionBanner>
        )
    },
})
