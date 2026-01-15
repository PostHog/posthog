import { SDK_KEY_TO_SNIPPET_LANGUAGE } from 'lib/constants'

import { SDKKey } from '~/types'

// Helper to get flag implementation Step components (not wrapped in Steps)
export const getFlagImplementationSteps = (
    sdkKey: SDKKey,
    Step: any,
    Markdown: any,
    snippets: any
): React.ReactElement[] => {
    const language = SDK_KEY_TO_SNIPPET_LANGUAGE[sdkKey] || 'javascript'
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    return [
        <Step key="basic-flag" title="Basic flag implementation" badge="required">
            {BooleanFlag && <BooleanFlag language={language} />}
        </Step>,
        <Step key="multivariate-flag" title="Multivariate flags" badge="optional">
            {MultivariateFlag && <MultivariateFlag language={language} />}
        </Step>,
        <Step key="experiments" title="Running experiments" badge="optional">
            <Markdown>
                Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an
                experiment by creating a new experiment in the PostHog dashboard.
            </Markdown>
        </Step>,
    ]
}

// Helper to get flag implementation Step components for SSR (client + server)
export const getFlagImplementationStepsSSR = (
    clientSDKKey: SDKKey,
    serverSDKKey: SDKKey,
    Step: any,
    Markdown: any,
    snippets: any
): React.ReactElement[] => {
    const clientLanguage = SDK_KEY_TO_SNIPPET_LANGUAGE[clientSDKKey] || 'javascript'
    const serverLanguage = SDK_KEY_TO_SNIPPET_LANGUAGE[serverSDKKey] || 'javascript'
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    return [
        <Step key="client-rendering" title="Client-side rendering" badge="required">
            <Markdown>**Basic flag implementation**</Markdown>
            {BooleanFlag && <BooleanFlag language={clientLanguage} />}
            <Markdown>**Multivariate flags**</Markdown>
            {MultivariateFlag && <MultivariateFlag language={clientLanguage} />}
        </Step>,
        <Step key="server-rendering" title="Server-side rendering" badge="required">
            <Markdown>**Basic flag implementation**</Markdown>
            {BooleanFlag && <BooleanFlag language={serverLanguage} />}
            <Markdown>**Multivariate flags**</Markdown>
            {MultivariateFlag && <MultivariateFlag language={serverLanguage} />}
        </Step>,
        <Step key="experiments" title="Running experiments" badge="optional">
            <Markdown>
                Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an
                experiment by creating a new experiment in the PostHog dashboard.
            </Markdown>
        </Step>,
    ]
}
