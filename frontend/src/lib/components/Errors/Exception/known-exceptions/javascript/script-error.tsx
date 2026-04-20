import { Link } from '@posthog/lemon-ui'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return exception.value.startsWith('Script error') && exception.type === 'Error'
    },
    render() {
        return (
            <KnownExceptionBanner>
                This error occurs when JavaScript exceptions are thrown from a third-party script but details are hidden
                due to cross-origin restrictions.{' '}
                <Link
                    to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-script-error-with-no-stack-traces"
                    target="_blank"
                >
                    Read our docs
                </Link>{' '}
                to learn how to get the full exception context.
            </KnownExceptionBanner>
        )
    },
})
