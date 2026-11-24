import { WarehouseExplainerAvailable } from './WarehouseExplainerAvailable'
import { WarehouseExplainerDetails } from './WarehouseExplainerDetails'
import { WarehouseExplainerHero } from './WarehouseExplainerHero'

/** What Warehouse home shows for an organization without a managed warehouse. */
export function WarehouseExplainer(): JSX.Element {
    return (
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
            <WarehouseExplainerHero />
            <WarehouseExplainerDetails />
            <WarehouseExplainerAvailable />
        </div>
    )
}
