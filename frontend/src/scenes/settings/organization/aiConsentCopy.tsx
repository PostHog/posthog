import { dayjs } from 'lib/dayjs'

export function getExternalAIProvidersTooltipTitle(): string {
    return `As of ${dayjs().format('MMMM YYYY')}: Anthropic and OpenAI`
}

export function AIHipaaDisclaimer(): JSX.Element {
    return (
        <p className="text-muted text-xs leading-relaxed">
            This feature is not HIPAA-compliant and is not intended for the processing of Protected Health Information
            ("PHI"). Any Business Associate Agreement ("BAA") you may have entered into with PostHog does not apply to
            this functionality. You are responsible for ensuring your use complies with applicable laws and regulations.
        </p>
    )
}
