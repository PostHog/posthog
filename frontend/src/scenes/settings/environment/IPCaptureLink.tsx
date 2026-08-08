import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function IPCaptureLink(): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            to={urls.settings('project-privacy', 'datacapture')}
            sideIcon={<IconArrowRight />}
        >
            Go to Privacy settings
        </LemonButton>
    )
}
