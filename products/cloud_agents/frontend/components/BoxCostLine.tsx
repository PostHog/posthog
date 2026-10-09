import { useValues } from 'kea'

import type { SizeNameEnumApi } from '../generated/api.schemas'
import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { describeBoxCost } from '../utils/pricing'

/** The price of the selected box in words, under a box size select. */
export function BoxCostLine({
    sizeName,
    minutes,
    fallback,
}: {
    sizeName: SizeNameEnumApi | null
    minutes: number
    /** The text when no size is selected. */
    fallback: string
}): JSX.Element {
    const { sizes, rates } = useValues(cloudAgentsCatalogLogic)
    const size = sizes.find((candidate) => candidate.name === sizeName)
    return (
        <p className="text-secondary text-xs m-0" data-attr="cloud-agents-box-cost-line">
            <span translate="no">{size && rates ? `${describeBoxCost(size, minutes, rates)}.` : fallback}</span>{' '}
            <span>Compute is billed per second.</span>
        </p>
    )
}
