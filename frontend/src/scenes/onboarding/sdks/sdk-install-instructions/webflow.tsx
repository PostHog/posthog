import { JSSnippet } from 'lib/components/JSSnippet'

export function SDKInstallWebflowInstructions(): JSX.Element {
    return (
        <>
            <h3>Install the PostHog web snippet</h3>
            <p>First copy your web snippet:</p>
            <JSSnippet />
            <p>
                Go to your Webflow site settings by clicking on the menu icon in the top left. If you haven’t already,
                sign up for at least the <strong>Basic</strong> site plan. This enables you to add custom code. Then:
            </p>
            <ol>
                <li>
                    Go to the <strong>Custom code</strong> tab in site settings.
                </li>
                <li>
                    In the <strong>Head code</strong> section, paste your PostHog snippet and press save.
                </li>
                <li> Publish your site.</li>
            </ol>
        </>
    )
}
