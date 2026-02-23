import { afterMount, beforeUnmount, connect, kea, listeners, path, selectors } from 'kea'

import { liveEventsLogic } from 'scenes/activity/live/liveEventsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProjectNoticeVariant, navigationLogic } from './navigationLogic'
import type { projectNoticeLogicType } from './projectNoticeLogicType'

const POLL_INTERVAL_MS = 30_000
const DEBOUNCE_MS = 2000

export const projectNoticeLogic = kea<projectNoticeLogicType>([
    path(['layout', 'navigation', 'projectNoticeLogic']),
    connect(() => ({
        values: [navigationLogic, ['projectNoticeVariant']],
        actions: [teamLogic, ['loadCurrentTeam'], liveEventsLogic, ['addEvents']],
    })),
    selectors({
        shouldPoll: [
            (s) => [s.projectNoticeVariant],
            (variant: ProjectNoticeVariant | null): boolean => variant === 'real_project_with_no_events',
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        addEvents: () => {
            if (!values.shouldPoll) {
                return
            }
            if (cache.debounceTimer) {
                clearTimeout(cache.debounceTimer)
            }
            cache.debounceTimer = window.setTimeout(() => {
                actions.loadCurrentTeam()
                cache.debounceTimer = null
            }, DEBOUNCE_MS)
        },
    })),
    afterMount(({ actions, values, cache }) => {
        if (values.shouldPoll) {
            cache.pollTimer = window.setInterval(() => {
                actions.loadCurrentTeam()
            }, POLL_INTERVAL_MS)
        }
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
