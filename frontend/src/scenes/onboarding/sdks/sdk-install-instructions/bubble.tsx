import { JSSnippet } from 'lib/components/JSSnippet'

export function SDKInstallBubbleInstructions(): JSX.Element {
    return (
        <>
            <h3>Install the PostHog web snippet</h3>
            <p>First copy your web snippet:</p>
            <JSSnippet />
            <p>
                Go to your Bubble site settings by clicking on the icon in the left-hand menu. If you haven’t already,
                sign up for at least the <strong>Starter</strong> site plan. This enables you to add custom code. Then:
            </p>
            <ol>
                <li>
                    Go to the <strong>SEO / metatags</strong> tab in site settings.
                </li>
                <li>
                    Paste your PostHog snippet in the <strong>Script/meta tags in header</strong> section.
                </li>
                <li> Deploy your site to live.</li>
            </ol>
        </>
    )
}
