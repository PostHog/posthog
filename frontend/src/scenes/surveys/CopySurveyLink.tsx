import { LemonButton } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function CopySurveyLink({ surveyId, className }: { surveyId: string; className?: string }): JSX.Element {
    return (
        <LemonButton
            icon={<IconLink />}
            onClick={() => {
                const url = new URL(window.location.origin)
                url.pathname = `/external_surveys/${surveyId}`
                copyToClipboard(url.toString(), 'survey link')
            }}
            className={className}
            size="small"
            tooltip="Responses are anonymous. Add the distinct_id query parameter to identify respondents."
        >
            Copy URL
        </LemonButton>
    )
}
