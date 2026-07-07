import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import { Experiment } from '~/types'

import { experimentMetricsLogic } from './experimentMetricsLogic'
import type { experimentResultsNotificationLogicType } from './experimentResultsNotificationLogicType'

export interface ExperimentResultsNotificationLogicProps {
    experiment: Experiment
}

// How long a recalculation must run before we offer the "notify me when ready" banner.
const NOTIFICATION_OFFER_DELAY_MS = 10_000

/**
 * Standalone "results are taking a while" notification for the recalculation flow: offers a banner
 * once a recalculation has been running for a bit, and (if the user opts in) fires a browser
 * notification when it finishes. Driven entirely by `experimentMetricsLogic.isRecalculating` so it's
 * decoupled from how results are loaded. The legacy equivalent still lives in experimentLogic.
 */
export const experimentResultsNotificationLogic = kea<experimentResultsNotificationLogicType>([
    props({} as ExperimentResultsNotificationLogicProps),
    key((props) => props.experiment.id),
    path((key) => ['scenes', 'experiment', 'experimentResultsNotificationLogic', String(key)]),
    connect((props: ExperimentResultsNotificationLogicProps) => ({
        values: [experimentMetricsLogic({ experiment: props.experiment }), ['isRecalculating']],
    })),
    actions({
        setShowNotificationOffer: (show: boolean) => ({ show }),
        setNotifyWhenResultsReady: (notify: boolean) => ({ notify }),
        dismissNotificationOffer: true,
        subscribeToResultsNotification: true,
        notifyResultsReady: true,
    }),
    reducers({
        showNotificationOffer: [
            false,
            {
                setShowNotificationOffer: (_, { show }) => show,
                dismissNotificationOffer: () => false,
            },
        ],
        notifyWhenResultsReady: [
            false,
            {
                setNotifyWhenResultsReady: (_, { notify }) => notify,
                dismissNotificationOffer: () => false,
            },
        ],
    }),
    listeners(({ props, values, actions, cache }) => ({
        dismissNotificationOffer: () => {
            // Stop the pending offer timer so it can't re-show the banner after the user dismissed it.
            cache.disposables.dispose('notificationOfferTimer')
        },
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
            cache.disposables.dispose('notificationOfferTimer')
            actions.setShowNotificationOffer(false)
            actions.setNotifyWhenResultsReady(false)
        },
    })),
    /**
     * Subscriptions (not listeners) on purpose: we react to the EDGE of `isRecalculating`, a derived
     * boolean composed from two upstream actions (setCurrentRecalculation + setRecalculationLoading) on
     * experimentMetricsLogic. There's no single action whose handler cleanly expresses "the derived value
     * just flipped", so this is the skill's sanctioned subscriptions case. The (next, prev) args give us
     * the transition for free instead of hand-tracking a previous value across two listeners.
     */
    subscriptions(({ actions, cache }) => ({
        isRecalculating: (isRecalculating: boolean, previous: boolean | undefined) => {
            if (isRecalculating && !previous) {
                /**
                 * A recalculation just started: offer the banner after it has been running a while. The
                 * timer must keep running while the tab is hidden (the point is to notify a user who has
                 * navigated away), so it opts out of pause-on-page-hide.
                 */
                cache.disposables.add(
                    () => {
                        const timer = setTimeout(
                            () => actions.setShowNotificationOffer(true),
                            NOTIFICATION_OFFER_DELAY_MS
                        )
                        return () => clearTimeout(timer)
                    },
                    'notificationOfferTimer',
                    { pauseOnPageHidden: false }
                )
            } else if (!isRecalculating && previous) {
                // Fire the notification (if subscribed) and reset the offer.
                actions.notifyResultsReady()
            }
        },
    })),
])
