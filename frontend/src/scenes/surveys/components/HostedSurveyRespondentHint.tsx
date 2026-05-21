import { Link } from '@posthog/lemon-ui'

export function HostedSurveyRespondentHint({ className }: { className?: string }): JSX.Element {
    return (
        <p className={className ?? 'text-xs text-muted'}>
            Responses are anonymous by default. Append <code>?distinct_id=...</code> to the URL to tie responses to a
            specific person.{' '}
            <Link
                to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                target="_blank"
            >
                Learn more
            </Link>
        </p>
    )
}
