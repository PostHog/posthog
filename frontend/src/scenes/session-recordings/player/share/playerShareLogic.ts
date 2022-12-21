import { kea, key, path, props, reducers, selectors, connect } from 'kea'
import { forms } from 'kea-forms'
import { colonDelimitedDuration, reverseColonDelimitedDuration, toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
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
    connect({
        values: [teamLogic, ['currentTeam']],
    }),

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

    selectors(({ props, values }) => ({
        url: [
            (s) => [s.shareUrl, s.shareUrlHasErrors],
            (shareUrl, hasErrors) => {
                const params = {
                    t:
                        shareUrl.includeTime && !hasErrors
                            ? reverseColonDelimitedDuration(shareUrl.time) || 0
                            : undefined,
                    team_id: values.currentTeam?.id,
                }
                return `${window.location.origin}${urls.sessionRecording(props.id)}?${toParams(params)}`
            },
        ],
    })),
])
