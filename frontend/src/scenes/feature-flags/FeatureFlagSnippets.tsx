import React from 'react'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { IconExternalLink } from 'lib/components/icons'
import { teamLogic } from 'scenes/teamLogic'

export const UTM_TAGS = '?utm_medium=in-product&utm_campaign=feature-flag'

export function JSSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // run your activation code here
}`}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a
                    target="_blank"
                    rel="noopener"
                    href={`https://posthog.com/docs/integrations/js-integration${UTM_TAGS}#feature-flags`}
                >
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}

export function PythonSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`if posthog.feature_enabled("${flagKey}", "user_distinct_id"):
    runAwesomeFeature()
`}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a
                    target="_blank"
                    rel="noopener"
                    href={`https://posthog.com/docs/integrations/python-integration${UTM_TAGS}#feature-flags`}
                >
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}

export function APISnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${window.location.origin}/decide/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]"
}'
                `}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a target="_blank" rel="noopener" href={`https://posthog.com/docs/api/feature-flags${UTM_TAGS}`}>
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}
