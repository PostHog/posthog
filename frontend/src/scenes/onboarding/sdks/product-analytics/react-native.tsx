import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SDKInstallRNInstructions } from '../sdk-install-instructions'

export function ProductAnalyticsRNInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRNInstructions />
            <h3 className="mt-4">Send an Event</h3>
            <CodeSnippet language={Language.JSX}>{`// With hooks
import { usePostHog } from 'posthog-react-native'

const MyComponent = () => {
    const posthog = usePostHog()

    useEffect(() => {
        posthog.capture("MyComponent loaded", { foo: "bar" })
    }, [])
}
        `}</CodeSnippet>
        </>
    )
}
