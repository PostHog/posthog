import { defineKnownException } from '../registry'
import { KnownExceptionBanner } from './base'

defineKnownException({
    match(exception) {
        return exception.type === 'Error' && (exception.value?.startsWith('ResizeObserver loop') ?? false)
    },
    render() {
        return (
            <KnownExceptionBanner>
                A ResizeObserver callback changed layout repeatedly, so the browser deferred the remaining notifications
                to the next frame. It sends no code location with this error, so there is no stack trace to show.
            </KnownExceptionBanner>
        )
    },
})
