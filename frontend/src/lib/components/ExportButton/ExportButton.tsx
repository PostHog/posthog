import { useMountedLogic } from 'kea'
import { forwardRef } from 'react'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, ExporterFormat, OnlineExportContext } from '~/types'

import { TriggerExportProps } from './exporter'

export interface ExportButtonItem {
    title?: string | React.ReactNode
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
    /** Produce the file in the browser instead of asking the server to render an export. */
    onClick?: () => void
    disabledReason?: string
}

export interface ExportButtonProps extends Pick<
    LemonButtonProps,
    'disabledReason' | 'icon' | 'sideIcon' | 'id' | 'type' | 'fullWidth'
> {
    items: ExportButtonItem[]
    buttonCopy?: string
    size?: LemonButtonProps['size']
}

export const ExportButton: React.FunctionComponent<ExportButtonProps & React.RefAttributes<HTMLButtonElement>> =
    forwardRef(function ExportButton({ items, buttonCopy, ...buttonProps }, ref): JSX.Element {
        useMountedLogic(exportsLogic)

        const { actions } = exportsLogic
        const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
            actions.startExport(triggerExportProps)
        }

        // Creating an export requires editor access to the export resource. It is applied per format
        // rather than to the whole menu, because a format produced in the browser creates no export
        // asset: it rasterizes what the person is already looking at, which they can screenshot anyway.
        const accessControlDisabledReason = getAccessControlDisabledReason(
            AccessControlResourceType.Export,
            AccessControlLevel.Editor
        )
        const hasBrowserRenderedFormat = items.some((item) => !!item.onClick)

        return (
            <LemonButtonWithDropdown
                ref={ref}
                data-attr="export-button"
                {...buttonProps}
                disabledReason={
                    buttonProps.disabledReason ??
                    (hasBrowserRenderedFormat ? undefined : (accessControlDisabledReason ?? undefined))
                }
                dropdown={{
                    actionable: true,
                    placement: 'right-start',
                    closeParentPopoverOnClickInside: true,
                    overlay: (
                        <>
                            <h5>File type</h5>
                            <LemonDivider />
                            {items.map(({ title, onClick, disabledReason, ...triggerExportProps }, i) => {
                                const exportFormatExtension = (
                                    Object.keys(ExporterFormat).find(
                                        (key) =>
                                            ExporterFormat[key as keyof typeof ExporterFormat] ===
                                            triggerExportProps.export_format
                                    ) ?? triggerExportProps.export_format
                                ).toLowerCase()
                                // A browser-rendered format rasterizes what the person already sees, so it reports
                                // no server export target.
                                const rendersInBrowser = !!onClick
                                const itemDisabledReason =
                                    disabledReason ??
                                    (rendersInBrowser ? undefined : (accessControlDisabledReason ?? undefined))

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
                                        disabledReason={itemDisabledReason}
                                        onClick={() => (onClick ? onClick() : void onExportClick(triggerExportProps))}
                                        data-attr={`export-button-${exportFormatExtension}`}
                                        data-ph-capture-attribute-export-target={rendersInBrowser ? null : target}
                                        data-ph-capture-attribute-export-body={
                                            !rendersInBrowser && exportBody.length ? JSON.stringify(exportBody) : null
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
