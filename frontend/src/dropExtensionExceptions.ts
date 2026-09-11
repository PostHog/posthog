import { BeforeSendFn } from 'posthog-js'

interface RawExceptionFrame {
    filename?: string
}

// URL schemes that only foreign scripts use. Browser extensions inject content scripts under
// their own scheme (chrome-extension://, moz-extension://, ...), Safari masks extension URLs as
// webkit-masked-url://, and extensions bundled with webpack declare a webpack://<name>/ source for
// their injected scripts. The PostHog app always serves its own runtime code from http(s)://, so a
// raw frame under any of these schemes is never first-party.
const EXTENSION_FRAME_SCHEMES = [
    'chrome-extension://',
    'moz-extension://',
    'safari-extension:',
    'safari-web-extension:',
    'webkit-masked-url:',
    'webpack://',
]

const isExtensionFrame = (frame: RawExceptionFrame): boolean =>
    typeof frame.filename === 'string' && EXTENSION_FRAME_SCHEMES.some((scheme) => frame.filename!.startsWith(scheme))

/**
 * Drop exceptions whose every stack frame comes from a browser extension.
 *
 * Extensions inject scripts into the PostHog app the same as any other page. When one throws,
 * posthog-js marks the frame `in_app` and cymbal keeps that value, so error tracking files the
 * throw as a high-severity first-party issue that no PostHog code can cause (for example a `[MobX]`
 * error from `webpack://jam-extension/...`, a dependency the app does not ship). posthog-js already
 * drops the known extension URL schemes before capture, but not webpack-namespaced injected
 * bundles, so those reach the app's before_send hook.
 *
 * The event is dropped only when every frame is extension-origin, because a genuine app error
 * always has at least one frame served from the app itself.
 */
export const dropExtensionOriginExceptions: BeforeSendFn = (event) => {
    if (event?.event !== '$exception') {
        return event
    }
    const exceptionList = event.properties?.$exception_list
    if (!Array.isArray(exceptionList)) {
        return event
    }
    const frames: RawExceptionFrame[] = exceptionList.flatMap((exception) => exception?.stacktrace?.frames ?? [])
    if (frames.length === 0) {
        return event
    }
    return frames.every(isExtensionFrame) ? null : event
}
