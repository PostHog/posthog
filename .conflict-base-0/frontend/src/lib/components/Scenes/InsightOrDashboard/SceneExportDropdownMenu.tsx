import { IconDownload } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ExportContext, ExporterFormat, OnlineExportContext } from '~/types'

import { TriggerExportProps } from '../../ExportButton/exporter'
import { exportsLogic } from '../../ExportButton/exportsLogic'
import { SubscriptionBaseProps } from '../../Subscriptions/utils'

interface SceneExportDropdownMenuProps extends SubscriptionBaseProps {
    dropdownMenuItems: {
        label?: string
        dataAttr: string
        format: ExporterFormat
        insight?: number
        dashboard?: number
        context?: ExportContext
    }[]
}

export function SceneExportDropdownMenu({ dropdownMenuItems }: SceneExportDropdownMenuProps): JSX.Element | null {
    const { actions } = exportsLogic

    const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
        actions.startExport(triggerExportProps)
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem>
                    <IconDownload />
                    Export
                    <DropdownMenuOpenIndicator className="ml-auto" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" matchTriggerWidth>
                {dropdownMenuItems.map((item, index) => {
                    const exportFormatExtension = Object.keys(ExporterFormat)
                        .find((key) => ExporterFormat[key as keyof typeof ExporterFormat] === item.format)
                        ?.toLowerCase()

                    let target: string
                    let exportBody: string = ''
                    if (item.insight) {
                        target = `insight-${item.insight}`
                    } else if (item.dashboard) {
                        target = `dashboard-${item.dashboard}`
                    } else if ('path' in (item.context || {})) {
                        target = (item.context as OnlineExportContext)?.path || 'unknown'
                        exportBody = (item.context as OnlineExportContext)?.body || 'unknown'
                    } else {
                        target = 'unknown'
                    }

                    return (
                        <DropdownMenuItem
                            key={index}
                            onClick={() =>
                                void onExportClick({
                                    export_format: item.format,
                                    ...(item.insight && { insight: item.insight }),
                                    ...(item.dashboard && { dashboard: item.dashboard }),
                                    ...(item.context && { export_context: item.context }),
                                })
                            }
                            data-attr={`export-button-${exportFormatExtension}`}
                            data-ph-capture-attribute-export-target={target}
                            data-ph-capture-attribute-export-body={
                                exportBody.length ? JSON.stringify(exportBody) : null
                            }
                            asChild
                        >
                            <ButtonPrimitive menuItem>
                                {item.label ? item.label : `.${exportFormatExtension}`}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )
                })}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
