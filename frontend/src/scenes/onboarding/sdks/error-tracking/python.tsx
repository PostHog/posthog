import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { PythonSetupSnippet, SDKInstallPythonInstructions } from '../sdk-install-instructions'

export function PythonInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPythonInstructions enableExceptionAutocapture />
            <p>
                If you're using Django, you can enable the exception autocapture middleware which will also
                automatically capture Django errors.
            </p>
            <CodeSnippet language={Language.Python}>
                MIDDLEWARE += ["posthog.integrations.django.PosthogContextMiddleware”]
            </CodeSnippet>
            <PythonSetupSnippet enableExceptionAutocapture />
            <h4>Optional: Capture exceptions manually</h4>
            <p>If you'd like, you can manually capture exceptions that you handle in your application.</p>
            <CodeSnippet language={Language.Python}>
                posthog.capture_exception(error, 'user_distinct_id', properties=additional_properties)
            </CodeSnippet>
        </>
    )
}
