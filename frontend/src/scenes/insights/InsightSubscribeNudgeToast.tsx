import { IconBell } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    openSubscriptionFromNudge,
    SUBSCRIPTION_PREFILL_PARAMS,
} from 'products/subscriptions/frontend/components/Subscriptions/subscriptionNudge'

export function insightSubscribeNudgeToastId(insightId: number): string {
    return `insight-subscribe-nudge-${insightId}`
}

export function showInsightSubscribeNudgeToast(
    insightId: number,
    insightShortId: string,
    insightName: string | null | undefined,
    viewCount7d: number
): void {
    lemonToast.info(
        <div className="flex flex-col gap-1.5 py-1 pr-1 min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconBell className="size-4 shrink-0 text-primary" />
                <span>You keep coming back to {insightName || 'this insight'}</span>
            </div>
            <div className="flex flex-col items-start gap-1.5 ml-5.5">
                <div className="text-xs text-secondary leading-snug">
                    You’ve viewed it {viewCount7d} times in the last week. Get it delivered to your inbox every Monday
                    instead.
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    className="!mx-0"
                    data-attr="insight-subscribe-nudge-toast-cta"
                    onClick={() =>
                        openSubscriptionFromNudge(
                            { insightShortId: insightShortId as any },
                            {
                                toastId: insightSubscribeNudgeToastId(insightId),
                                via: SUBSCRIPTION_PREFILL_PARAMS.viaToast,
                            }
                        )
                    }
                >
                    Set up subscription
                </LemonButton>
            </div>
        </div>,
        { toastId: insightSubscribeNudgeToastId(insightId), autoClose: false, icon: false }
    )
}
