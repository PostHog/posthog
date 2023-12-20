import { kea, path, props, selectors } from 'kea'

import type { exporterViewLogicType } from './exporterViewLogicType'
import { ExportedData } from './types'

// This is a simple logic that is mounted by the Exporter view and then can be found by any nested callers
// This simplifies passing props everywhere.
// E.g. api.ts uses this to add the sharing_access_token
export const exporterViewLogic = kea<exporterViewLogicType>([
    path(() => ['scenes', 'exporter', 'exporterLogic']),
    props({} as ExportedData),
    selectors(() => ({
        exportedData: [() => [(_, props) => props], (props): ExportedData => props],
    })),
])

export const getCurrentExporterData = (): ExportedData | undefined => {
    return exporterViewLogic.findMounted()?.values.exportedData
}
