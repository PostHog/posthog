import { WarehouseExplainerAvailable } from './WarehouseExplainerAvailable'
import { WarehouseExplainerDetails } from './WarehouseExplainerDetails'
import { WarehouseExplainerHero } from './WarehouseExplainerHero'

/** What the warehouse upsell page shows for an organization without a warehouse. */
export function WarehouseExplainer(): JSX.Element {
    return (
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
            <WarehouseExplainerHero />
            <WarehouseExplainerDetails />
            <WarehouseExplainerAvailable />
        </div>
    )
}
