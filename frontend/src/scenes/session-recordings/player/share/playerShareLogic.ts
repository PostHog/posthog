import { kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { colonDelimitedDuration, reverseColonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { playerShareLogicType } from './playerShareLogicType'

export type PlayerShareLogicProps = {
    seconds: number | null
    id: string
}

export const playerShareLogic = kea<playerShareLogicType>([
    path(() => ['scenes', 'session-recordings', 'player', 'playerShareLogic']),
    props({} as PlayerShareLogicProps),
    key((props: PlayerShareLogicProps) => `${props.id}-${props.seconds}`),

    reducers({
        loading: [
            true,
            {
                loadRecordingMetaSuccess: () => false,
            },
        ],
    }),

    forms(({ props }) => ({
        shareUrl: {
            defaults: { includeTime: false, time: colonDelimitedDuration(props.seconds, null) } as {
                time: string | null
                includeTime: boolean
            },
            errors: ({ time, includeTime }) => ({
                time:
                    time && includeTime && reverseColonDelimitedDuration(time || undefined) === null
                        ? 'Set a valid time like 02:30 (minutes:seconds)'
                        : undefined,
            }),
        },
    })),

    selectors(({ props }) => ({
        url: [
            (s) => [s.shareUrl, s.shareUrlHasErrors],
            (shareUrl, hasErrors) => {
                const url = `${window.location.origin}${urls.sessionRecording(props.id)}`
                return (
                    url +
                    (shareUrl.includeTime && !hasErrors
                        ? `?t=${reverseColonDelimitedDuration(shareUrl.time) || 0}`
                        : '')
                )
            },
        ],
    })),
])
