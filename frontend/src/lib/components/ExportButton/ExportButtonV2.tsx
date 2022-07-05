import React from 'react'
import { LemonButton, LemonButtonProps, LemonButtonWithPopup } from '../LemonButton'
import { ExporterFormat } from './exporterLogic'
import { LemonDivider } from '../LemonDivider'
import { triggerExport } from './exporter'

export interface ExportButtonItemResource {
    method?: 'GET' | 'POST'
    path: string
    body?: any
    filename?: string
}

export interface ExportButtonItem {
    title?: string
    format: ExporterFormat
    resource: ExportButtonItemResource
}

export interface ExportButtonProps extends Pick<LemonButtonProps, 'icon' | 'type' | 'fullWidth'> {
    items: ExportButtonItem[]
}

export function ExportButtonV2({ items, ...buttonProps }: ExportButtonProps): JSX.Element {
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
                        {items.map((item) => (
                            <LemonButton
                                key={`${item.format}-${item.resource.path}`}
                                fullWidth
                                type="stealth"
                                onClick={() =>
                                    triggerExport({
                                        export_format: item.format,
                                        export_context: item.resource,
                                    })
                                }
                                data-attr={`export-button-${item.format.split('/').pop()}`}
                            >
                                {item.title ? item.title : `.${item.format.split('/').pop()}`}
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
