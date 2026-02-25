import { afterMount, beforeUnmount, connect, kea, path } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { projectNoticeLogicType } from './projectNoticeLogicType'

const POLL_INTERVAL_MS = 30_000

export const projectNoticeLogic = kea<projectNoticeLogicType>([
    path(['layout', 'navigation', 'projectNoticeLogic']),
    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeam']],
    })),
    afterMount(({ actions, cache }) => {
        cache.pollTimer = window.setInterval(() => {
            actions.loadCurrentTeam()
        }, POLL_INTERVAL_MS)
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollTimer) {
            clearInterval(cache.pollTimer)
        }
        if (cache.debounceTimer) {
            clearTimeout(cache.debounceTimer)
        }
    }),
])
