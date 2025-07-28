import { LemonButton } from '@posthog/lemon-ui'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function CopySurveyLink({ surveyId }: { surveyId: string }): JSX.Element {
    return (
        <LemonButton
            icon={<IconLink />}
            onClick={() => {
                const url = new URL(window.location.origin)
                url.pathname = `/external_surveys/${surveyId}`
                copyToClipboard(url.toString(), 'survey link')
            }}
        >
            Copy survey external link
        </LemonButton>
    )
}
