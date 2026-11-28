import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import type { RealtimeCohortsJoinStateEnumApi } from '../generated/api.schemas'
import { realtimeCohortsJoinLogic } from './realtimeCohortsJoinLogic'

type ShownJoinState = Exclude<RealtimeCohortsJoinStateEnumApi, 'serving' | 'available'>

interface JoinBanner {
    type: 'info' | 'warning'
    text: string
    dismissKey?: (teamId: number | null) => string
}

const BANNERS: Record<ShownJoinState, JoinBanner> = {
    setting_up: {
        type: 'info',
        text: 'Setting up real-time cohorts for this project. This usually takes about a minute.',
    },
    // pinned: the dismiss keys are localStorage keys, so renaming one shows the banner again to everyone who closed it
    not_open: {
        type: 'info',
        text: "Real-time cohorts aren't open to new projects yet. This project will join once they are.",
        dismissKey: () => 'realtime-cohorts-join-not-open',
    },
    refused: {
        type: 'warning',
        text: "Real-time cohorts couldn't be turned on for this project automatically. Contact support and we'll take a look.",
        // A refusal belongs to one project, so closing it in one project leaves it showing in the others.
        dismissKey: (teamId) => `realtime-cohorts-join-refused-${teamId}`,
    },
    failed: {
        type: 'warning',
        text: "Setting up real-time cohorts for this project didn't finish. We'll try again in about an hour.",
    },
}

export function RealtimeCohortsJoinBanner(): JSX.Element | null {
    const { joinState, currentTeamId } = useValues(realtimeCohortsJoinLogic)
    if (joinState === null || joinState === 'serving' || joinState === 'available') {
        return null
    }

    const { type, text, dismissKey } = BANNERS[joinState]
    // The tracker goes inside, because its wrapper div would still render around a dismissed banner and leave a gap.
    // It captures once per instance, so the key gives each state its own instance and its own view event.
    return (
        <LemonBanner type={type} dismissKey={dismissKey?.(currentTeamId)}>
            <PostHogCaptureOnViewed
                key={joinState}
                name="realtime-cohorts-join-banner-shown"
                properties={{ state: joinState }}
            >
                {text}
            </PostHogCaptureOnViewed>
        </LemonBanner>
    )
}
