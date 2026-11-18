import { useActions } from 'kea'
import { useEffect } from 'react'

import { MetricsStarterDashboardForm } from 'products/metrics/frontend/components/MetricsStarterDashboardForm'
import { metricsStarterDashboardLogic } from 'products/metrics/frontend/components/metricsStarterDashboardLogic'

export function ObservabilityDashboardForm({ onClose }: { onClose: () => void }): JSX.Element {
    const { loadServices, loadMetricOptions, closeModal } = useActions(metricsStarterDashboardLogic)

    useEffect(() => {
        loadServices({})
        loadMetricOptions({})
        return () => closeModal()
    }, [loadServices, loadMetricOptions, closeModal])

    return (
        <div className="max-w-2xl mx-auto">
            <p className="text-secondary">
                Start with metrics for a service. You can add logs, error tracking and product analytics to the same
                dashboard.
            </p>
            <p className="text-secondary text-xs">Starts with the last hour of data. Auto refresh stays off.</p>
            <MetricsStarterDashboardForm onCancel={onClose} onCreated={onClose} />
        </div>
    )
}
