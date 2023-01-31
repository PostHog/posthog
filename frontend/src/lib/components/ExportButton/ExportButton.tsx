import { ExporterFormat } from '~/types'
import { LemonButton, LemonButtonProps, LemonButtonWithPopup } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { triggerExport, TriggerExportProps } from './exporter'

export interface ExportButtonItem {
    title?: string
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
}

export interface ExportButtonProps extends Pick<LemonButtonProps, 'icon' | 'type' | 'status' | 'fullWidth'> {
    items: ExportButtonItem[]
}

export function ExportButton({ items, ...buttonProps }: ExportButtonProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            status="stealth"
            data-attr="export-button"
            {...buttonProps}
            popup={{
                actionable: true,
                placement: 'right-start',
                closeParentPopupOnClickInside: true,
                overlay: (
                    <>
                        <h5>File type</h5>
                        <LemonDivider />
                        {items.map(({ title, ...triggerExportProps }, i) => {
                            const exportFormatExtension = triggerExportProps.export_format.split('/').pop()

                            return (
                                <LemonButton
                                    key={i}
                                    fullWidth
                                    status="stealth"
                                    onClick={() => triggerExport(triggerExportProps)}
                                    data-attr={`export-button-${exportFormatExtension}`}
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
        </LemonButtonWithPopup>
    )
}
