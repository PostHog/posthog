import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function DocusaurusInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                Add PostHog to your{' '}
                <Link to="https://docusaurus.io/" target="_blank">
                    Docusaurus
                </Link>{' '}
                documentation site using the official plugin.
            </p>
            <h4>Install the plugin</h4>
            <CodeSnippet language={Language.Bash}>npm install --save posthog-docusaurus</CodeSnippet>
            <h4>Configure</h4>
            <p>
                Add the plugin to your <code>docusaurus.config.js</code>:
            </p>
            <CodeSnippet language={Language.JavaScript}>
                {`module.exports = {
  plugins: [
    [
      'posthog-docusaurus',
      {
        apiKey: '${currentTeam?.api_token}',
        appUrl: '${apiHostOrigin()}',
        enableInDevelopment: false,
      },
    ],
  ],
}`}
            </CodeSnippet>
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}
