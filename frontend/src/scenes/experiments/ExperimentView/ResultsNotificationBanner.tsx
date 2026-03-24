import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'

export function ResultsNotificationBanner(): JSX.Element | null {
    const {
        showNotificationOffer,
        notifyWhenResultsReady,
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
    } = useValues(experimentLogic)
    const { subscribeToResultsNotification, dismissNotificationOffer } = useActions(experimentLogic)

    const isLoading = primaryMetricsResultsLoading || secondaryMetricsResultsLoading

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
            onClose={notifyWhenResultsReady ? undefined : dismissNotificationOffer}
        >
            {notifyWhenResultsReady ? (
                "We'll notify you when results are ready. Keep this tab open."
            ) : (
                <div className="flex items-center gap-2">
                    <span>Results are taking a while.</span>
                    <LemonButton type="secondary" size="xsmall" onClick={subscribeToResultsNotification}>
                        Notify me when ready
                    </LemonButton>
                </div>
            )}
        </LemonBanner>
    )
}
