import { JSEventCapture, JSHtmlSnippet, JSInitSnippet } from '@posthog/shared-onboarding/product-analytics'

import { useJsSnippetConfig } from 'lib/components/JSSnippet'

import { SDK_DEFAULTS_DATE } from '~/loadPostHogJS'

// In-app wrappers that inject Kea store values into the shared docs snippet components
export const InAppJSHtmlSnippet = (): JSX.Element => {
    const config = useJsSnippetConfig()
    return <JSHtmlSnippet {...config} />
}

export const InAppJSInitSnippet = (): JSX.Element => {
    return <JSInitSnippet defaultsDate={SDK_DEFAULTS_DATE} />
}

// Shared JS web snippet map used across multiple onboarding flows
export const JS_WEB_SNIPPETS = {
    JSEventCapture,
    JSHtmlSnippet: InAppJSHtmlSnippet,
    JSInitSnippet: InAppJSInitSnippet,
}
