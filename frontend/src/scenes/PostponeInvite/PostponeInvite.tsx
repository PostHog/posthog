import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { postponeInviteLogic } from './postponeInviteLogic'

export const scene: SceneExport = {
    component: PostponeInvite,
    logic: postponeInviteLogic,
}

function formatSendAt(isoString: string): string {
    return dayjs(isoString).format('MMMM D, YYYY [at] h:mm A')
}

export function PostponeInvite(): JSX.Element {
    const {
        invite,
        inviteLoading,
        loadErrorMessage,
        result,
        resultLoading,
        customDate,
        tonightAvailable,
        submittingOption,
        submitErrorMessage,
    } = useValues(postponeInviteLogic)
    const { setCustomDate, postponeByOption, postponeCustom } = useActions(postponeInviteLogic)

    let content: JSX.Element
    if (inviteLoading) {
        content = <SpinnerOverlay sceneLevel />
    } else if (result) {
        content = (
            <div className="text-center">
                <h2>You're all set</h2>
                <p>
                    We'll send the invitation to join <strong>{invite?.organization_name}</strong> again on{' '}
                    <strong>{formatSendAt(result.scheduled_send_at)}</strong>.
                </p>
            </div>
        )
    } else if (loadErrorMessage || !invite) {
        content = (
            <div className="text-center">
                <h2>This link can't be used</h2>
                <p>{loadErrorMessage ?? 'This link is invalid or has expired.'}</p>
            </div>
        )
    } else {
        // While a request is in flight, block every trigger to prevent double-submission.
        const scheduling = resultLoading ? 'Scheduling…' : undefined
        content = (
            <div className="flex flex-col gap-2">
                <div className="text-center">
                    <h2>Remind me later</h2>
                    <p>
                        We'll send the invitation to join <strong>{invite.organization_name}</strong> again at a time
                        that works better for you.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    loading={submittingOption === 'hour'}
                    disabledReason={scheduling}
                    onClick={() => postponeByOption('hour')}
                >
                    In an hour
                </LemonButton>
                {tonightAvailable && (
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        loading={submittingOption === 'tonight'}
                        disabledReason={scheduling}
                        onClick={() => postponeByOption('tonight')}
                    >
                        Tonight
                    </LemonButton>
                )}
                <LemonButton
                    type="secondary"
                    fullWidth
                    center
                    loading={submittingOption === 'tomorrow'}
                    disabledReason={scheduling}
                    onClick={() => postponeByOption('tomorrow')}
                >
                    Tomorrow
                </LemonButton>
                <div className="flex flex-col gap-2 mt-2">
                    <LemonCalendarSelectInput
                        granularity="minute"
                        value={customDate}
                        onChange={setCustomDate}
                        placeholder="Pick a custom date and time"
                        clearable
                    />
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        loading={submittingOption === 'custom'}
                        disabledReason={!customDate ? 'Pick a custom date and time first' : scheduling}
                        onClick={postponeCustom}
                    >
                        Postpone to selected time
                    </LemonButton>
                </div>
                {submitErrorMessage && <p className="text-danger text-center">{submitErrorMessage}</p>}
            </div>
        )
    }

    return <BridgePage view="postpone-invite">{content}</BridgePage>
}

export default PostponeInvite
