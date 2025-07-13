import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { supportLogic } from './Support/supportLogic'

export const FeedbackNotice = ({ text }: { text: string }): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions = preflight?.cloud

    return (
        <LemonBanner type="info" className="my-4">
            <div className="flex items-center flex-wrap gap-2 justify-between">
                <div className="flex-1 min-w-full sm:min-w-0">{text}</div>
                {showSupportOptions ? (
                    <span className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconBug />}
                            onClick={() => openSupportForm({ kind: 'bug', isEmailFormOpen: true })}
                        >
                            Report a bug
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconFeedback />}
                            onClick={() => openSupportForm({ kind: 'feedback', isEmailFormOpen: true })}
                        >
                            Give feedback
                        </LemonButton>
                    </span>
                ) : null}
            </div>
        </LemonBanner>
    )
}
