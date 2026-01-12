import { Link } from '@posthog/lemon-ui'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return !!exception.value.match(/React(?:\.js)?(?: DOM)?(?: production)? error #(\d+)/i)
    },
    render(exception) {
        const errorCode = exception.value.match(/React(?:\.js)?(?: DOM)?(?: production)? error #(\d+)/i)
        return (
            <KnownExceptionBanner>
                React minifies error messages as part of its production build process to reduce bundle size, and does
                not include a stack trace. You can visit the{' '}
                <Link to={`https://react.dev/errors/${errorCode}`} target="_blank">
                    React docs
                </Link>{' '}
                to see the full description of the error or{' '}
                <Link
                    to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-minified-react-error-with-no-stack-traces"
                    target="_blank"
                >
                    read our docs
                </Link>{' '}
                to learn how you might be able to debug this issue.
            </KnownExceptionBanner>
        )
    },
})
