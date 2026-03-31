import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { BuildJsHtmlSnippetConfig, buildJsHtmlSnippet } from './js-snippet-builder'

export type JSHtmlSnippetProps = BuildJsHtmlSnippetConfig

export const JSHtmlSnippet = (props: JSHtmlSnippetProps): JSX.Element => {
    const { CodeBlock } = useMDXComponents()
    const snippet = buildJsHtmlSnippet(props)

    return <CodeBlock blocks={[{ language: 'html', file: 'HTML', code: snippet }]} />
}
