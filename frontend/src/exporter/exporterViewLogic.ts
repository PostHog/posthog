import { kea, path, props, selectors } from 'kea'
import { ExportedData } from './types'

import type { exporterViewLogicType } from './exporterViewLogicType'

// This is a simple logic that is mounted by the Exporter view and then can be found by any nested callers
// This simplifies passing props everywhere
export const exporterViewLogic = kea<exporterViewLogicType>([
    path(() => ['scenes', 'exporter', 'exporterLogic']),
    props({} as ExportedData),
    selectors(() => ({
        exportedData: [() => [(_, props) => props], (props): ExportedData => props],
    })),
])

export const getCurrentExporterData = (): ExportedData | undefined => {
    exporterViewLogic.findMounted()?.values.exportedData
}
