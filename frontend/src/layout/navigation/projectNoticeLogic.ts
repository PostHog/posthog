import { afterMount, beforeUnmount, connect, kea, listeners, path } from 'kea'

import { liveEventsLogic } from 'scenes/activity/live/liveEventsLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { projectNoticeLogicType } from './projectNoticeLogicType'

const POLL_INTERVAL_MS = 30_000
const DEBOUNCE_MS = 2000

export const projectNoticeLogic = kea<projectNoticeLogicType>([
    path(['layout', 'navigation', 'projectNoticeLogic']),
    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeam'], liveEventsLogic, ['addEvents']],
    })),
    listeners(({ actions, cache }) => ({
        addEvents: () => {
            if (cache.debounceTimer) {
                clearTimeout(cache.debounceTimer)
            }
            cache.debounceTimer = window.setTimeout(() => {
                actions.loadCurrentTeam()
                cache.debounceTimer = null
            }, DEBOUNCE_MS)
        },
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
