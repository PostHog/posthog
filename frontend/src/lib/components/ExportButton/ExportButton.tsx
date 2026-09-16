import { useMountedLogic } from 'kea'
import { forwardRef, useState } from 'react'

import {
    ExportColumn,
    ExportColumnsModal,
    TABULAR_EXPORT_FORMATS,
} from 'lib/components/ExportButton/ExportColumnsModal'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, ExporterFormat, OnlineExportContext } from '~/types'

import { TriggerExportProps, exportFormatExtension } from './exporter'

export interface ExportButtonItem {
    title?: string | React.ReactNode
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
}

export interface ExportButtonProps extends Pick<
    LemonButtonProps,
    'disabledReason' | 'icon' | 'sideIcon' | 'id' | 'type' | 'fullWidth'
> {
    items: ExportButtonItem[]
    buttonCopy?: string
    size?: LemonButtonProps['size']
    /** When given, the tabular formats can be exported with a subset of these columns. */
    columns?: ExportColumn[]
}

export const ExportButton: React.FunctionComponent<ExportButtonProps & React.RefAttributes<HTMLButtonElement>> =
    forwardRef(function ExportButton({ items, buttonCopy, columns, ...buttonProps }, ref): JSX.Element {
        useMountedLogic(exportsLogic)
        const [isColumnsModalOpen, setIsColumnsModalOpen] = useState(false)

        const { actions } = exportsLogic
        const onExportClick = async (triggerExportProps: TriggerExportProps): Promise<void> => {
            actions.startExport(triggerExportProps)
        }

        const tabularItems = items.filter(
            (item) =>
                TABULAR_EXPORT_FORMATS.includes(item.export_format) &&
                item.export_context &&
                !('localData' in item.export_context)
        )
        const canSelectColumns = !!columns?.length && tabularItems.length > 0

        // Creating an export requires editor access to the export resource.
        const accessControlDisabledReason = getAccessControlDisabledReason(
            AccessControlResourceType.Export,
            AccessControlLevel.Editor
        )

        return (
            <>
                <LemonButtonWithDropdown
                    ref={ref}
                    data-attr="export-button"
                    {...buttonProps}
                    disabledReason={buttonProps.disabledReason ?? accessControlDisabledReason ?? undefined}
                    dropdown={{
                        actionable: true,
                        placement: 'right-start',
                        closeParentPopoverOnClickInside: true,
                        overlay: (
                            <>
                                <h5>File type</h5>
                                <LemonDivider />
                                {items.map(({ title, ...triggerExportProps }, i) => {
                                    const extension = exportFormatExtension(triggerExportProps.export_format)

                                    let target: string
                                    let exportBody: string = ''
                                    if (triggerExportProps.insight) {
                                        target = `insight-${triggerExportProps.insight}`
                                    } else if (triggerExportProps.dashboard) {
                                        target = `dashboard-${triggerExportProps.dashboard}`
                                    } else if ('path' in (triggerExportProps.export_context || {})) {
                                        target =
                                            (triggerExportProps.export_context as OnlineExportContext)?.path ||
                                            'unknown'
                                        exportBody =
                                            (triggerExportProps.export_context as OnlineExportContext)?.body ||
                                            'unknown'
                                    } else {
                                        target = 'unknown'
                                    }

                                    return (
                                        <LemonButton
                                            key={i}
                                            fullWidth
                                            onClick={() => void onExportClick(triggerExportProps)}
                                            data-attr={`export-button-${extension}`}
                                            data-ph-capture-attribute-export-target={target}
                                            data-ph-capture-attribute-export-body={
                                                exportBody.length ? JSON.stringify(exportBody) : null
                                            }
                                        >
                                            {title ? title : `.${extension}`}
                                        </LemonButton>
                                    )
                                })}
                                {canSelectColumns && (
                                    <>
                                        <LemonDivider />
                                        <LemonButton
                                            fullWidth
                                            onClick={() => setIsColumnsModalOpen(true)}
                                            data-attr="export-button-select-columns"
                                        >
                                            Select columns…
                                        </LemonButton>
                                    </>
                                )}
                            </>
                        ),
                    }}
                >
                    {buttonCopy ?? 'Export'}
                </LemonButtonWithDropdown>
                {canSelectColumns && isColumnsModalOpen && (
                    <ExportColumnsModal
                        isOpen
                        columns={columns}
                        formats={tabularItems.map((item) => item.export_format)}
                        onClose={() => setIsColumnsModalOpen(false)}
                        onExport={(format, selectedColumns) => {
                            const item = tabularItems.find((candidate) => candidate.export_format === format)
                            if (!item?.export_context) {
                                return
                            }
                            void onExportClick({
                                export_format: item.export_format,
                                dashboard: item.dashboard,
                                insight: item.insight,
                                export_context: { ...item.export_context, columns: selectedColumns },
                            })
                        }}
                    />
                )}
            </>
        )
    })
