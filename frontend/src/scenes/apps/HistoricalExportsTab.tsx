import React from 'react'
import { Collapse } from 'antd'
import { useActions, useValues } from 'kea'
import { appMetricsSceneLogic, HistoricalExportInfo } from './appMetricsSceneLogic'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { HistoricalExport } from './HistoricalExport'

export function HistoricalExportsTab(): JSX.Element {
    const { openExportSections, historicalExports, historicalExportsLoading, pluginConfig } =
        useValues(appMetricsSceneLogic)
    const { setOpenExportSections } = useActions(appMetricsSceneLogic)

    if (historicalExportsLoading || !pluginConfig) {
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
                        <HistoricalExport pluginConfigId={pluginConfig.id} jobId={historicalExport.job_id} />
                    </Collapse.Panel>
                ))}
            </Collapse>
        </>
    )
}
