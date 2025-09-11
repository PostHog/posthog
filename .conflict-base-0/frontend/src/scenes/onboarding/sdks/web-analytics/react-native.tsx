import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { WebAnalyticsMobileFinalSteps } from 'scenes/onboarding/sdks/web-analytics/FinalSteps'

import { SDKInstallRNInstructions } from '../sdk-install-instructions'

export function WebAnalyticsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions />
            <h3 className="mt-4">Optional: Send a manual event</h3>
            <p>Our package will autocapture events for you, but you can manually define events, too!</p>
            <CodeSnippet language={Language.JSX}>{`// With hooks
import { usePostHog } from 'posthog-react-native'

const MyComponent = () => {
    const posthog = usePostHog()

    useEffect(() => {
        posthog.capture("MyComponent loaded", { foo: "bar" })
    }, [])
}
        `}</CodeSnippet>
            <WebAnalyticsMobileFinalSteps />
        </>
    )
}
