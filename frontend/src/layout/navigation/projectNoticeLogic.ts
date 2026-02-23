import { connect, kea, listeners, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { liveEventsLogic } from 'scenes/activity/live/liveEventsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProjectNoticeVariant, navigationLogic } from './navigationLogic'
import type { projectNoticeLogicType } from './projectNoticeLogicType'

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
            // Debounce team checks when events stream in
            if (cache.eventDebounceTimer) {
                clearTimeout(cache.eventDebounceTimer)
            }
            cache.eventDebounceTimer = window.setTimeout(() => {
                actions.loadCurrentTeam()
                cache.eventDebounceTimer = null
            }, DEBOUNCE_MS)
        },
    })),
    subscriptions(({ actions, cache }) => ({
        shouldPoll: (shouldPoll: boolean) => {
            if (shouldPoll) {
                cache.disposables.add(() => {
                    const timerId = window.setInterval(() => {
                        actions.loadCurrentTeam()
                    }, 30_000)
                    return () => clearInterval(timerId)
                }, 'noEventsPolling')
            } else {
                cache.disposables.dispose('noEventsPolling')
                // Clean up debounce timer if banner dismissed
                if (cache.eventDebounceTimer) {
                    clearTimeout(cache.eventDebounceTimer)
                    cache.eventDebounceTimer = null
                }
            }
        },
    })),
])
