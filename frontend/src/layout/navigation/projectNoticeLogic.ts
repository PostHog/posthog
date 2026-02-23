import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { ProjectNoticeVariant, navigationLogic } from './navigationLogic'
import type { projectNoticeLogicType } from './projectNoticeLogicType'

export const projectNoticeLogic = kea<projectNoticeLogicType>([
    path(['layout', 'navigation', 'projectNoticeLogic']),
    connect(() => ({
        values: [navigationLogic, ['projectNoticeVariant']],
        actions: [teamLogic, ['loadCurrentTeam']],
    })),
    selectors({
        shouldPoll: [
            (s) => [s.projectNoticeVariant],
            (variant: ProjectNoticeVariant | null): boolean => variant === 'real_project_with_no_events',
        ],
    }),
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
            }
        },
    })),
])
