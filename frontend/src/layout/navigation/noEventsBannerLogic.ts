import { afterMount, connect, kea, path } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { noEventsBannerLogicType } from './noEventsBannerLogicType'

const POLL_INTERVAL_MS = 30_000

export const noEventsBannerLogic = kea<noEventsBannerLogicType>([
    path(['layout', 'navigation', 'noEventsBannerLogic']),
    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeam']],
    })),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            const pollTimer = window.setInterval(() => {
                actions.loadCurrentTeam()
            }, POLL_INTERVAL_MS)
            return () => clearInterval(pollTimer)
        })
    }),
])
