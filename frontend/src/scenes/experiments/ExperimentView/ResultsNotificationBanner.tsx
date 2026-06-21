import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { experimentResultsNotificationLogic } from '../experimentResultsNotificationLogic'
import { isSavedExperiment } from '../utils'

/**
 * "Results are taking a while" banner. On the recalculation flow it reads the standalone
 * experimentResultsNotificationLogic (driven by isRecalculating); the legacy flow keeps reading the
 * equivalent state on experimentLogic.
 */
export function ResultsNotificationBanner(): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const recalculationFlow = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]

    if (recalculationFlow && isSavedExperiment(experiment)) {
        return <RecalculationNotificationBanner experiment={experiment} />
    }
    return <LegacyNotificationBanner />
}

function NotificationBannerView({
    showNotificationOffer,
    notifyWhenResultsReady,
    isLoading,
    onSubscribe,
    onDismiss,
}: {
    showNotificationOffer: boolean
    notifyWhenResultsReady: boolean
    isLoading: boolean
    onSubscribe: () => void
    onDismiss: () => void
}): JSX.Element | null {
    useEffect(() => {
        if (!notifyWhenResultsReady || !isLoading) {
            return
        }
        const handler = (e: BeforeUnloadEvent): void => {
            e.preventDefault()
        }
        window.addEventListener('beforeunload', handler)
        return () => window.removeEventListener('beforeunload', handler)
    }, [notifyWhenResultsReady, isLoading])

    if (!showNotificationOffer && !notifyWhenResultsReady) {
        return null
    }
    if (!isLoading) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mb-4"
            icon={<IconClock />}
            onClose={notifyWhenResultsReady ? undefined : onDismiss}
        >
            {notifyWhenResultsReady ? (
                "We'll notify you when results are ready. Keep this tab open."
            ) : (
                <div className="flex items-center gap-2">
                    <span>Results are taking a while.</span>
                    <LemonButton type="secondary" size="xsmall" onClick={onSubscribe}>
                        Notify me when ready
                    </LemonButton>
                </div>
            )}
        </LemonBanner>
    )
}

function RecalculationNotificationBanner({ experiment }: { experiment: Experiment }): JSX.Element | null {
    const notificationLogic = experimentResultsNotificationLogic({ experiment })
    const { showNotificationOffer, notifyWhenResultsReady } = useValues(notificationLogic)
    const { subscribeToResultsNotification, dismissNotificationOffer } = useActions(notificationLogic)
    const { isRecalculating } = useValues(experimentMetricsLogic({ experiment }))

    return (
        <NotificationBannerView
            showNotificationOffer={showNotificationOffer}
            notifyWhenResultsReady={notifyWhenResultsReady}
            isLoading={isRecalculating}
            onSubscribe={subscribeToResultsNotification}
            onDismiss={dismissNotificationOffer}
        />
    )
}

function LegacyNotificationBanner(): JSX.Element | null {
    const {
        showNotificationOffer,
        notifyWhenResultsReady,
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
    } = useValues(experimentLogic)
    const { subscribeToResultsNotification, dismissNotificationOffer } = useActions(experimentLogic)

    return (
        <NotificationBannerView
            showNotificationOffer={showNotificationOffer}
            notifyWhenResultsReady={notifyWhenResultsReady}
            isLoading={primaryMetricsResultsLoading || secondaryMetricsResultsLoading}
            onSubscribe={subscribeToResultsNotification}
            onDismiss={dismissNotificationOffer}
        />
    )
}
