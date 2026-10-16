import { JSSnippet } from 'lib/components/JSSnippet'

export function SDKInstallFramerInstructions(): JSX.Element {
    return (
        <>
            <h3>Install the PostHog web snippet</h3>
            <p>First copy your web snippet:</p>
            <JSSnippet />
            <p>
                Then go to your Framer project settings by clicking the gear in the top right. If you haven’t already,
                sign up for at least the <strong>Mini</strong> site plan. This enables you to add custom code. Then:
            </p>
            <ol>
                <li>
                    Go to the <strong>General</strong> tab in site settings.
                </li>
                <li>
                    Scroll down to the <strong>Custom Code</strong> section.
                </li>
                <li>
                    {' '}
                    Under{' '}
                    <strong>
                        End of <code>&lt;head&gt;</code> tag
                    </strong>
                    , paste your PostHog snippet.
                </li>
                <li> Press save, and then publish your site.</li>
            </ol>
        </>
    )
}
