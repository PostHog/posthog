import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { NewMetricModal } from '../components/NewMetricModal'
import { metricsLogic } from '../metricsLogic'

/**
 * Create button for the data catalog empty state. Metrics are created in a modal that
 * the scene normally renders, and the gate replaces the scene - so the empty state has
 * to render the modal itself or the button would open nothing.
 */
export function DataCatalogPrimaryAction(): JSX.Element {
    const { openNewMetricModal } = useActions(metricsLogic)

    return (
        <>
            <LemonButton type="primary" onClick={openNewMetricModal} data-attr="data-catalog-new-metric-button">
                Define your first metric
            </LemonButton>
            <NewMetricModal />
        </>
    )
}
