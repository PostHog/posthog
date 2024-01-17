import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { BatchExportsList } from 'scenes/batch_exports/BatchExportsListScene'

import { AvailableFeature } from '~/types'

export function BatchExportsTab(): JSX.Element {
    return (
        <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
            <BatchExportsList />
        </PayGateMini>
    )
}
