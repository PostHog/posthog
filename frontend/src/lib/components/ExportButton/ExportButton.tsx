import React from 'react'
import { ExporterFormat } from '~/types'
import { LemonButton, LemonButtonProps, LemonButtonWithPopup } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
import { triggerExport, TriggerExportProps } from './exporter'

export interface ExportButtonItem {
    title?: string
    export_format: ExporterFormat
    export_context?: TriggerExportProps['export_context']
    dashboard?: number
    insight?: number
}

export interface ExportButtonProps extends Pick<LemonButtonProps, 'icon' | 'type' | 'fullWidth'> {
    items: ExportButtonItem[]
}

export function ExportButton({ items, ...buttonProps }: ExportButtonProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            type="stealth"
            data-attr="export-button"
            {...buttonProps}
            popup={{
                actionable: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <h5>File type</h5>
                        <LemonDivider />
                        {items.map(({ title, ...triggerExportProps }, i) => (
                            <LemonButton
                                key={i}
                                fullWidth
                                type="stealth"
                                onClick={() => triggerExport(triggerExportProps)}
                                data-attr={`export-button-${i}`}
                            >
                                {title ? title : `.${triggerExportProps.export_format.split('/').pop()}`}
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
