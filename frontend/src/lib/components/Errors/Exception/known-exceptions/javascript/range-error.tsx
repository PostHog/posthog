import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return exception.type === 'RangeError'
    },
    render() {
        return (
            <KnownExceptionBanner>
                <strong>RangeError</strong> is thrown when a numeric value is outside its allowed range — typical causes
                are stack overflows from infinite recursion, oversized typed arrays, or invalid date or number arguments
                to native APIs that don&apos;t emit a JS stack trace. Resolved stack frames require uploaded source maps
                —{' '}
                <Link to={`${urls.errorTrackingConfiguration()}#selectedSetting=error-tracking-symbol-sets`}>
                    check your symbol sets
                </Link>{' '}
                or{' '}
                <Link to="https://posthog.com/docs/error-tracking/upload-source-maps" target="_blank">
                    read the source map docs
                </Link>{' '}
                to learn more.
            </KnownExceptionBanner>
        )
    },
})
