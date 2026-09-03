import { useActions } from 'kea'

import { IconDownload } from '@posthog/icons'

import { ButtonPrimitive, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import {
    AccessControlLevel,
    AccessControlResourceType,
    ExportContext,
    ExporterFormat,
    OnlineExportContext,
} from '~/types'

import { SubscriptionBaseProps } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { TriggerExportProps } from '../../ExportButton/exporter'
import { exportsLogic } from '../../ExportButton/exportsLogic'

interface SceneExportDropdownMenuProps extends SubscriptionBaseProps {
    disabledReasons?: DisabledReasonsObject
    dropdownMenuItems: {
        label?: string
        dataAttr: string
        format: ExporterFormat
        insight?: number
        dashboard?: number
        context?: ExportContext
        /** Produce the file in the browser instead of asking the server to render an export. */
        onClick?: () => void
        /** Reasons this one format cannot be produced, keyed by the message to show. */
        disabledReasons?: DisabledReasonsObject
    }[]
}

export function SceneExportDropdownMenu({
    dropdownMenuItems,
    disabledReasons,
    insightShortId,
}: SceneExportDropdownMenuProps): JSX.Element | null {
    const { startExport } = useActions(exportsLogic)

    const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
        startExport(triggerExportProps)
    }

    // Creating an export requires editor access to the export resource. It is applied per format rather
    // than to the whole menu, because a format produced in the browser creates no export asset: it
    // rasterizes what the person is already looking at, which they can screenshot anyway.
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )
    const hasBrowserRenderedFormat = dropdownMenuItems.some((item) => !!item.onClick)
    const resolvedDisabledReasons: DisabledReasonsObject = {
        ...disabledReasons,
        ...(!hasBrowserRenderedFormat && accessControlDisabledReason ? { [accessControlDisabledReason]: true } : {}),
    }

    const isDisabled = Object.values(resolvedDisabledReasons).some(Boolean)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={isDisabled}>
                <ButtonPrimitive menuItem disabledReasons={resolvedDisabledReasons}>
                    <IconDownload />
                    Export
                    <MenuOpenIndicator className="ml-auto" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" matchTriggerWidth>
                <DropdownMenuGroup>
                    {dropdownMenuItems.map((item, index) => {
                        const rendersInBrowser = !!item.onClick
                        const itemDisabledReasons: DisabledReasonsObject = {
                            ...item.disabledReasons,
                            ...(!rendersInBrowser && accessControlDisabledReason
                                ? { [accessControlDisabledReason]: true }
                                : {}),
                        }
                        const itemDisabled = Object.values(itemDisabledReasons).some(Boolean)
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
                                disabled={itemDisabled}
                                onClick={() => {
                                    if (itemDisabled) {
                                        return
                                    }
                                    if (item.onClick) {
                                        item.onClick()
                                        return
                                    }
                                    void onExportClick({
                                        export_format: item.format,
                                        ...(item.insight && { insight: item.insight }),
                                        ...(insightShortId && { insightShortId }),
                                        ...(item.dashboard && { dashboard: item.dashboard }),
                                        ...(item.context && { export_context: item.context }),
                                    })
                                }}
                                data-attr={`export-button-${exportFormatExtension}`}
                                data-ph-capture-attribute-export-target={rendersInBrowser ? null : target}
                                data-ph-capture-attribute-export-body={
                                    !rendersInBrowser && exportBody.length ? JSON.stringify(exportBody) : null
                                }
                                asChild
                            >
                                <ButtonPrimitive menuItem disabledReasons={itemDisabledReasons}>
                                    {item.label ? item.label : `.${exportFormatExtension}`}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        )
                    })}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
