import React from 'react'
import { Collapse } from 'antd'
import { useActions, useValues } from 'kea'
import { appMetricsSceneLogic, HistoricalExportInfo } from './appMetricsSceneLogic'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'

export function HistoricalExportsTab(): JSX.Element {
    const { openExportSections, historicalExports, historicalExportsLoading } = useValues(appMetricsSceneLogic)
    const { setOpenExportSections } = useActions(appMetricsSceneLogic)

    if (historicalExportsLoading) {
        return <LemonSkeleton />
    }

    return (
        <>
            <Collapse
                activeKey={openExportSections}
                onChange={(keys) => setOpenExportSections(keys as Array<HistoricalExportInfo['job_id']>)}
            >
                {historicalExports.map((historicalExport) => (
                    <Collapse.Panel header={historicalExport.job_id} key={historicalExport.job_id}>
                        <pre>{JSON.stringify(historicalExport, null, 2)}</pre>
                    </Collapse.Panel>
                ))}
            </Collapse>
        </>
    )
}
