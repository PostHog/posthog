import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { experimentLogic } from '../experimentLogic'

/**
 * Legacy "results are taking a while" banner. On the recalculation flow the RecalculationStatus bar
 * owns the notify affordance, so this renders nothing there.
 */
export function ResultsNotificationBanner(): JSX.Element | null {
    const recalculationFlow = useFeatureFlag('EXPERIMENTS_METRICS_RECALCULATION')

    if (recalculationFlow) {
        return null
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
