import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import type { RealtimeCohortsJoinStateEnumApi } from '../generated/api.schemas'
import { realtimeCohortsJoinLogic } from './realtimeCohortsJoinLogic'

type ShownJoinState = Exclude<RealtimeCohortsJoinStateEnumApi, 'serving' | 'available'>

const BANNERS: Record<ShownJoinState, { type: 'info' | 'warning'; text: string; dismissKey?: string }> = {
    setting_up: {
        type: 'info',
        text: 'Setting up realtime cohorts for this project. This usually takes about a minute.',
    },
    // pinned: the dismiss keys are localStorage keys, so renaming one shows the banner again to everyone who closed it
    not_open: {
        type: 'info',
        text: "Realtime cohorts aren't open to new projects yet. This project will join once they are.",
        dismissKey: 'realtime-cohorts-join-not-open',
    },
    refused: {
        type: 'warning',
        text: "Realtime cohorts couldn't be turned on for this project automatically. Contact support and we'll take a look.",
        dismissKey: 'realtime-cohorts-join-refused',
    },
    failed: {
        type: 'warning',
        text: "Setting up realtime cohorts for this project didn't finish. We'll try again in about an hour.",
    },
}

export function RealtimeCohortsJoinBanner(): JSX.Element | null {
    const { joinState } = useValues(realtimeCohortsJoinLogic)
    if (joinState === null || joinState === 'serving' || joinState === 'available') {
        return null
    }

    const { type, text, dismissKey } = BANNERS[joinState]
    // The tracker goes inside, because its wrapper div would still render around a dismissed banner and leave a gap.
    return (
        <LemonBanner type={type} dismissKey={dismissKey}>
            <PostHogCaptureOnViewed name="realtime-cohorts-join-banner-shown" properties={{ state: joinState }}>
                {text}
            </PostHogCaptureOnViewed>
        </LemonBanner>
    )
}
