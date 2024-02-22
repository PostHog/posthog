import { useMountedLogic } from 'kea'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { sidePanelExportsLogic } from '~/layout/navigation-3000/sidepanel/panels/exports/sidePanelExportsLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ExporterFormat, OnlineExportContext, SidePanelTab } from '~/types'

import { triggerExport, TriggerExportProps } from './exporter'

export interface ExportButtonItem {
    title?: string | React.ReactNode
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
}

export interface ExportButtonProps extends Pick<LemonButtonProps, 'icon' | 'type' | 'fullWidth'> {
    items: ExportButtonItem[]
}

export function ExportButton({ items, ...buttonProps }: ExportButtonProps): JSX.Element {
    useMountedLogic(sidePanelLogic)
    useMountedLogic(sidePanelExportsLogic)

    const { actions } = sidePanelLogic
    const { loadExports } = sidePanelExportsLogic.actions

    const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
        actions.openSidePanel(SidePanelTab.Exports)
        loadExports()
        await triggerExport(triggerExportProps)
        loadExports()
    }

    return (
        <LemonButtonWithDropdown
            data-attr="export-button"
            {...buttonProps}
            dropdown={{
                actionable: true,
                placement: 'right-start',
                closeParentPopoverOnClickInside: true,
                overlay: (
                    <>
                        <h5>File type</h5>
                        <LemonDivider />
                        {items.map(({ title, ...triggerExportProps }, i) => {
                            const exportFormatExtension = triggerExportProps.export_format.split('/').pop()

                            let target: string
                            let exportBody: string = ''
                            if (triggerExportProps.insight) {
                                target = `insight-${triggerExportProps.insight}`
                            } else if (triggerExportProps.dashboard) {
                                target = `dashboard-${triggerExportProps.dashboard}`
                            } else if ('path' in (triggerExportProps.export_context || {})) {
                                target = (triggerExportProps.export_context as OnlineExportContext)?.path || 'unknown'
                                exportBody =
                                    (triggerExportProps.export_context as OnlineExportContext)?.body || 'unknown'
                            } else {
                                target = 'unknown'
                            }

                            return (
                                <LemonButton
                                    key={i}
                                    fullWidth
                                    onClick={() => void onExportClick(triggerExportProps)}
                                    data-attr={`export-button-${exportFormatExtension}`}
                                    data-ph-capture-attribute-export-target={target}
                                    data-ph-capture-attribute-export-body={
                                        exportBody.length ? JSON.stringify(exportBody) : null
                                    }
                                >
                                    {title ? title : `.${exportFormatExtension}`}
                                </LemonButton>
                            )
                        })}
                    </>
                ),
            }}
        >
            Export
        </LemonButtonWithDropdown>
    )
}
