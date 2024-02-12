import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { BatchExportsList } from 'scenes/batch_exports/BatchExportsListScene'

import { AvailableFeature } from '~/types'

export function BatchExportsTab(): JSX.Element {
    return (
        <>
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
                <></>
            </PayGateMini>
            <BatchExportsList /> {/* We always show enabled batch exports */}
        </>
    )
}
