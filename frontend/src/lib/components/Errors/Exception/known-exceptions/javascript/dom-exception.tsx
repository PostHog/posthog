import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return exception.type === 'DOMException'
    },
    render() {
        return (
            <KnownExceptionBanner>
                <strong>DOMException</strong> is thrown from browser-native APIs (e.g. <code>fetch</code>,{' '}
                <code>AbortController</code>, IndexedDB, media APIs) and does not include a JavaScript stack trace.
                Resolved stack frames require uploaded source maps —{' '}
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
