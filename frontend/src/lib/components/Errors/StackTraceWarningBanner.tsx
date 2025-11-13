import { LemonBanner, Link } from '@posthog/lemon-ui'

import { ExceptionAttributes } from './types'

function isScriptError(exceptionAttributes: ExceptionAttributes): boolean {
    return (
        exceptionAttributes.type === 'Error' &&
        exceptionAttributes.runtime === 'web' &&
        exceptionAttributes.value === 'Script error'
    )
}

function isNonErrorPromiseRejection(exceptionAttributes: ExceptionAttributes): boolean {
    return exceptionAttributes.value?.startsWith('Non-Error promise rejection') ?? false
}

function minifiedReactErrorCode(exceptionAttributes: ExceptionAttributes): string | null {
    const match =
        exceptionAttributes && exceptionAttributes.value
            ? exceptionAttributes.value.match(/React(?:\.js)?(?: DOM)?(?: production)? error #(\d+)/i)
            : null

    return match ? match[1] : null
}

export const StackTraceWarningBanner = ({
    exceptionAttributes,
}: {
    exceptionAttributes: ExceptionAttributes
}): JSX.Element | null => {
    if (isScriptError(exceptionAttributes)) {
        return <LemonBanner type="warning">{scriptError}</LemonBanner>
    }

    if (isNonErrorPromiseRejection(exceptionAttributes)) {
        return <LemonBanner type="warning">{nonErrorPromiseRejection}</LemonBanner>
    }

    const errorCode = minifiedReactErrorCode(exceptionAttributes)

    if (errorCode) {
        return <LemonBanner type="warning">{minifiedReactError(errorCode)}</LemonBanner>
    }

    return null
}

const scriptError = (
    <>
        This error occurs when JavaScript exceptions are thrown from a third-party script but details are hidden due to
        cross-origin restrictions.{' '}
        <Link
            to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-script-error-with-no-stack-traces"
            target="_blank"
        >
            Read our docs
        </Link>{' '}
        to learn how to get the full exception context.
    </>
)
const minifiedReactError = (errorCode: string): JSX.Element => (
    <>
        React minifies error messages as part of its production build process to reduce bundle size, and does not
        include a stack trace. You can visit the{' '}
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
    </>
)

const nonErrorPromiseRejection = (
    <>
        This issue occurs when non Error objects are provided to Promise rejections. When you do this a stack trace is
        not captured as part of the caught exception.{' '}
        <Link
            to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-non-error-promise-rejection-error-with-no-stack-traces"
            target="_blank"
        >
            Read our docs
        </Link>{' '}
        to learn how to get the full exception context.
    </>
)
