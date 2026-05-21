import { Link } from '@posthog/lemon-ui'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return exception.type === 'TypeError' && exception.value === 'Load failed'
    },
    render() {
        return (
            <KnownExceptionBanner>
                <strong>Load failed</strong> is the message Safari emits when a <code>fetch()</code> call cannot
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
