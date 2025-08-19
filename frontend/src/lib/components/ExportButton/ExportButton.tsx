import { useMountedLogic } from 'kea'
import { forwardRef } from 'react'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { ExporterFormat, OnlineExportContext } from '~/types'

import { TriggerExportProps } from './exporter'

export interface ExportButtonItem {
    title?: string | React.ReactNode
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
}

export interface ExportButtonProps
    extends Pick<LemonButtonProps, 'disabledReason' | 'icon' | 'sideIcon' | 'id' | 'type' | 'fullWidth'> {
    items: ExportButtonItem[]
    buttonCopy?: string
}

export const ExportButton: React.FunctionComponent<ExportButtonProps & React.RefAttributes<HTMLButtonElement>> =
    forwardRef(function ExportButton({ items, buttonCopy, ...buttonProps }, ref): JSX.Element {
        useMountedLogic(exportsLogic)

        const { actions } = exportsLogic
        const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
            actions.startExport(triggerExportProps)
        }

        return (
            <LemonButtonWithDropdown
                ref={ref}
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
                                const exportFormatExtension = Object.keys(ExporterFormat)
                                    .find((key) => ExporterFormat[key as any] === triggerExportProps.export_format)
                                    ?.toLowerCase()

                                let target: string
                                let exportBody: string = ''
                                if (triggerExportProps.insight) {
                                    target = `insight-${triggerExportProps.insight}`
                                } else if (triggerExportProps.dashboard) {
                                    target = `dashboard-${triggerExportProps.dashboard}`
                                } else if ('path' in (triggerExportProps.export_context || {})) {
                                    target =
                                        (triggerExportProps.export_context as OnlineExportContext)?.path || 'unknown'
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
                {buttonCopy ?? 'Export'}
            </LemonButtonWithDropdown>
        )
    })
