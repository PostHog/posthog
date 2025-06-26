import { useMountedLogic } from 'kea'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { forwardRef } from 'react'

import { ExporterFormat, OnlineExportContext } from '~/types'

import { TriggerExportProps } from './exporter'
import { DropdownMenu, DropdownMenuItem, DropdownMenuContent, DropdownMenuTrigger, DropdownMenuOpenIndicator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { IconDownload, IconShare } from '@posthog/icons'

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
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive fullWidth>
                        <IconShare />
                        Export
                        <DropdownMenuOpenIndicator />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    {items.map(({ title, ...triggerExportProps }, i) => {
                        const exportFormatExtension = Object.keys(ExporterFormat)
                            .find((key) => ExporterFormat[key as keyof typeof ExporterFormat] === triggerExportProps.export_format)
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
                        return <DropdownMenuItem key={i} asChild>
                            <ButtonPrimitive 
                                fullWidth 
                                data-attr={`export-button-${exportFormatExtension}`} 
                                data-ph-capture-attribute-export-target={target} 
                                data-ph-capture-attribute-export-body={exportBody.length ? JSON.stringify(exportBody) : null}
                                onClick={() => void onExportClick(triggerExportProps)}
                            >
                                <IconDownload/> {title ? title : `.${exportFormatExtension}`}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    })}
                </DropdownMenuContent>
            </DropdownMenu>
        )
    })
