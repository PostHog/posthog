import { LemonBanner, Link } from '@posthog/lemon-ui'

import { defineKnownException } from '../registry'

defineKnownException({
    match(exception) {
        return exception.value?.startsWith('Non-Error promise rejection') ?? false
    },
    render() {
        return (
            <LemonBanner type="info">
                This issue occurs when non Error objects are provided to Promise rejections. When you do this a stack
                trace is not captured as part of the caught exception.{' '}
                <Link
                    to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-non-error-promise-rejection-error-with-no-stack-traces"
                    target="_blank"
                >
                    Read our docs
                </Link>{' '}
                to learn how to get the full exception context.
            </LemonBanner>
        )
    },
})
