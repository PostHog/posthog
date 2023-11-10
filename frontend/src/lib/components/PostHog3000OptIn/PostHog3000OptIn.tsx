import { IconClose } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconPresent } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { posthog3000OptInlogic } from './posthog3000OptInlogic'

export function PostHog3000OptInButton(props: Partial<LemonButtonProps>): JSX.Element | null {
    const { optIn } = useActions(posthog3000OptInlogic)
    return (
        <LemonButton
            type="primary"
            status="primary"
            fullWidth
            center
            icon={<IconPresent />}
            onClick={() => optIn()}
            {...props}
        >
            Try out the new design
        </LemonButton>
    )
}

export function PostHog3000OptIn(): JSX.Element | null {
    const { noticeDismissed } = useValues(posthog3000OptInlogic)
    const { dismissNotice } = useActions(posthog3000OptInlogic)
    const showOptIn = useFeatureFlag('POSTHOG_3000_PREVIEW')

    if (noticeDismissed || !showOptIn) {
        return null
    }

    return (
        <div className="bg-bg-light border-t p-3">
            <div className="flex items-center justify-between font-bold italic">
                <span>Pssstt!</span>
                <LemonButton status="stealth" size="small" icon={<IconClose />} onClick={dismissNotice} />
            </div>
            <p>
                We've got a preview of our new UI codenamed <b>PostHog 3000</b>. We'd love to hear what you think of it
                (and you can always come back to the old design)
            </p>
            <PostHog3000OptInButton />
        </div>
    )
}
