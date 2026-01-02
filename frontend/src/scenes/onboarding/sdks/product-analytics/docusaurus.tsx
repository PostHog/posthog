import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsDocusaurusInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://docusaurus.io/" target="_blank">
                    Docusaurus
                </Link>{' '}
                is a popular static site generator for documentation. You can add PostHog using the official plugin.
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
            <p>
                PostHog will now automatically capture pageviews and other events on your Docusaurus site. See the{' '}
                <Link
                    to="https://posthog.com/docs/libraries/docusaurus"
                    target="_blank"
                    targetBlankIcon
                    disableDocsPanel
                >
                    Docusaurus integration docs
                </Link>{' '}
                for more options.
            </p>
        </>
    )
}
