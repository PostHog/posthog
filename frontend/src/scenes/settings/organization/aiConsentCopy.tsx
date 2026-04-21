import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

export const AI_HIPAA_DISCLAIMER =
    'This feature is not HIPAA-compliant and is not intended for the processing of Protected Health Information ("PHI"). Any Business Associate Agreement ("BAA") you may have entered into with PostHog does not apply to this functionality. You are responsible for ensuring your use complies with applicable laws and regulations.'

export function ExternalAIProvidersTooltip({ children }: { children: React.ReactNode }): JSX.Element {
    return <Tooltip title={`As of ${dayjs().format('MMMM YYYY')}: Anthropic and OpenAI`}>{children}</Tooltip>
}
