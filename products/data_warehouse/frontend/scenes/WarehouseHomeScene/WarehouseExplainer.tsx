import { WarehouseExplainerAvailable } from './WarehouseExplainerAvailable'
import { WarehouseExplainerFeatures } from './WarehouseExplainerFeatures'
import { WarehouseExplainerHowItWorks } from './WarehouseExplainerHowItWorks'
import { WarehouseExplainerLead } from './WarehouseExplainerLead'
import { WarehouseExplainerSetup } from './WarehouseExplainerSetup'

/** What Warehouse home shows for an organization without a managed warehouse. */
export function WarehouseExplainer(): JSX.Element {
    return (
        <>
            <WarehouseExplainerLead />
            <WarehouseExplainerHowItWorks />
            <WarehouseExplainerFeatures />
            <WarehouseExplainerSetup />
            <WarehouseExplainerAvailable />
        </>
    )
}
