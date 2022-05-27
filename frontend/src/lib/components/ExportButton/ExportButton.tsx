import React from 'react'
import { LemonButton, LemonButtonProps, LemonButtonWithPopup } from '../LemonButton'
import { useActions, useValues } from 'kea'
import { ExporterFormat, exporterLogic } from './exporterLogic'
import { LemonDivider } from '../LemonDivider'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightShortId } from '~/types'

interface ExportButtonProps extends Pick<LemonButtonProps, 'icon' | 'type' | 'fullWidth'> {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export function ExportButton({ dashboardId, insightShortId, ...buttonProps }: ExportButtonProps): JSX.Element {
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insightShortId,
        doNotLoad: true,
    }

    const { supportsCsvExport, csvExportUrl, insight } = useValues(insightLogic(insightLogicProps))

    const { exportItem } = useActions(exporterLogic({ dashboardId, insightId: insight?.id }))
    const { exportInProgress } = useValues(exporterLogic({ dashboardId, insightId: insight?.id }))

    const supportedFormats: ExporterFormat[] = []

    if (dashboardId || insightShortId) {
        supportedFormats.push(ExporterFormat.PNG)
    }
    if (supportsCsvExport) {
        supportedFormats.push(ExporterFormat.CSV)
    }

    const onExportItemClick = (exportFormat: ExporterFormat): void => {
        // NOTE: Once we standardise the exporting code in the backend this can be removed
        if (exportFormat === ExporterFormat.CSV) {
            window.open(csvExportUrl, '_blank')
            return
        }

        exportItem(exportFormat)
    }

    return (
        <LemonButtonWithPopup
            type="stealth"
            loading={exportInProgress}
            data-attr="export-button"
            {...buttonProps}
            popup={{
                actionable: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <h5>File type</h5>
                        <LemonDivider />
                        {supportedFormats.map((format) => (
                            <LemonButton
                                key={format}
                                fullWidth
                                type="stealth"
                                onClick={() => onExportItemClick(format)}
                                data-attr={`export-button-${format.split('/').pop()}`}
                            >
                                .{format.split('/').pop()}
                            </LemonButton>
                        ))}
                    </>
                ),
            }}
        >
            Export
        </LemonButtonWithPopup>
    )
}
