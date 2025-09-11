import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsHeliconeInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://helicone.ai/" target="_blank">
                    Helicone
                </Link>{' '}
                supports most popular LLM models and you can bring your Helicone data into PostHog for analysis. To get
                started:
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    Sign up to{' '}
                    <Link to="https://www.helicone.ai/" target="_blank">
                        Helicone
                    </Link>{' '}
                    and add it to your LLM app.
                </li>
                <li>
                    Similar to how you add a{' '}
                    <Link
                        to="https://docs.helicone.ai/helicone-headers/header-directory#supported-headers"
                        target="_blank"
                    >
                        Helicone-Auth header
                    </Link>{' '}
                    when installing Helicone, add two new headers
                    <strong> Helicone-Posthog-Key</strong> and <strong>Helicone-Posthog-Host</strong> with your PostHog
                    details:
                    <CodeSnippet language={Language.Python}>
                        {`# Example for adding it to OpenAI in Python
                        
client = OpenAI(
api_key="your-api-key-here",  # Replace with your OpenAI API key
base_url="https://oai.hconeai.com/v1",  # Set the API endpoint
default_headers= { 
    "Helicone-Auth": f"Bearer {HELICONE_API_KEY}",
    "Helicone-Posthog-Key": "${currentTeam?.api_token}}",
    "Helicone-Posthog-Host": "${apiHostOrigin()}",
    }
)
                        `}
                    </CodeSnippet>
                </li>
            </ol>
            <p>Helicone events will now be exported into PostHog as soon as they're available.</p>
        </>
    )
}
