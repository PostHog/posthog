import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { combineUrl } from 'kea-router'
import { colonDelimitedDuration, reverseColonDelimitedDuration } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
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
        queryParams: [
            (s) => [s.shareUrl, s.shareUrlHasErrors],
            (shareUrl, hasErrors) => {
                if (!shareUrl.includeTime || hasErrors) {
                    return {}
                }
                return { t: `${reverseColonDelimitedDuration(shareUrl.time) || 0}` }
            },
        ],
        url: [
            (s) => [s.queryParams],
            (queryParams) => {
                const path = urls.project(getCurrentTeamId(), urls.replaySingle(props.id))
                return combineUrl(`${window.location.origin}${path}`, queryParams).url
            },
        ],
    })),
])
