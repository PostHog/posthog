import { Link } from '@posthog/lemon-ui'

export function HostedSurveyRespondentHint({ className }: { className?: string }): JSX.Element {
    return (
        <div className={`flex flex-col gap-1 text-muted ${className ?? 'text-xs'}`}>
            <div className="font-medium text-secondary">Customize the URL with query parameters:</div>
            <ul className="list-disc list-inside space-y-0.5 m-0">
                <li>
                    <code>?distinct_id=user_id</code> — tie the response to a specific person (use the same value as{' '}
                    <code>posthog.identify()</code>)
                </li>
                <li>
                    <code>?q0=2&amp;q1=8</code> — pre-fill answers for one-click surveys in emails (<code>q0</code> =
                    first question, value = choice or rating)
                </li>
                <li>
                    <code>?key=value</code> — any extra parameter is captured as an event property on the response
                </li>
            </ul>
            <Link
                to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                target="_blank"
            >
                Learn more about hosted survey URLs
            </Link>
        </div>
    )
}
