import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import { Experiment } from '~/types'

import { experimentMetricsLogic } from './experimentMetricsLogic'
import type { experimentResultsNotificationLogicType } from './experimentResultsNotificationLogicType'

export interface ExperimentResultsNotificationLogicProps {
    experiment: Experiment
}

/**
 * Browser notification for the recalculation flow: the status bar's "Notify me" button opts in, and a
 * notification fires when the run finishes. Driven entirely by `experimentMetricsLogic.isRecalculating`
 * so it's decoupled from how results are loaded. The legacy equivalent still lives in experimentLogic.
 */
export const experimentResultsNotificationLogic = kea<experimentResultsNotificationLogicType>([
    props({} as ExperimentResultsNotificationLogicProps),
    key((props) => props.experiment.id),
    path((key) => ['scenes', 'experiment', 'experimentResultsNotificationLogic', String(key)]),
    connect((props: ExperimentResultsNotificationLogicProps) => ({
        values: [experimentMetricsLogic({ experiment: props.experiment }), ['isRecalculating']],
    })),
    actions({
        setNotifyWhenResultsReady: (notify: boolean) => ({ notify }),
        subscribeToResultsNotification: true,
        notifyResultsReady: true,
    }),
    reducers({
        notifyWhenResultsReady: [
            false,
            {
                setNotifyWhenResultsReady: (_, { notify }) => notify,
            },
        ],
    }),
    listeners(({ props, values, actions, cache }) => ({
        subscribeToResultsNotification: async () => {
            if (!('Notification' in window)) {
                lemonToast.error('Your browser does not support notifications.')
                return
            }
            let permission = Notification.permission
            if (permission === 'default') {
                permission = await Notification.requestPermission()
            }
            if (permission === 'granted') {
                actions.setNotifyWhenResultsReady(true)
            } else if (permission === 'denied') {
                lemonToast.info(
                    'Notifications are blocked. Enable them in your browser address bar or system settings.'
                )
            }
        },
        setNotifyWhenResultsReady: ({ notify }) => {
            /**
             * Warn before closing the tab while subscribed: the notification can only fire from this page.
             * Must survive tab-hide (closing a background tab still fires beforeunload), so it opts out of
             * pause-on-page-hide.
             */
            if (notify) {
                cache.disposables.add(
                    () => {
                        const handler = (e: BeforeUnloadEvent): void => e.preventDefault()
                        window.addEventListener('beforeunload', handler)
                        return () => window.removeEventListener('beforeunload', handler)
                    },
                    'beforeUnloadGuard',
                    { pauseOnPageHidden: false }
                )
            } else {
                cache.disposables.dispose('beforeUnloadGuard')
            }
        },
        // Fire the browser notification (if subscribed) once a recalculation finishes.
        notifyResultsReady: () => {
            if (values.notifyWhenResultsReady && 'Notification' in window && Notification.permission === 'granted') {
                const notification = new Notification('Experiment results ready', {
                    body: `Results for "${props.experiment.name}" are now available.`,
                    icon: '/static/posthog-icon.svg',
                    tag: `experiment-results-${props.experiment.id}`,
                })
                notification.onclick = () => {
                    window.focus()
                    notification.close()
                }
            }
            actions.setNotifyWhenResultsReady(false)
        },
    })),
    /**
     * Subscriptions (not listeners) on purpose: we react to the EDGE of `isRecalculating`, a derived
     * boolean composed from two upstream actions (setCurrentRecalculation + setRecalculationLoading) on
     * experimentMetricsLogic. There's no single action whose handler cleanly expresses "the derived value
     * just flipped", so this is the skill's sanctioned subscriptions case.
     */
    subscriptions(({ actions }) => ({
        isRecalculating: (isRecalculating: boolean, previous: boolean | undefined) => {
            if (!isRecalculating && previous) {
                actions.notifyResultsReady()
            }
        },
    })),
])
