import React from 'react'
import { ExporterFormat } from '~/types'
import { LemonButton, LemonButtonProps, LemonButtonWithPopup } from '../LemonButton'
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
                        {items.map((item) => (
                            <LemonButton
                                key={`${item.format}-${item.resource.path}`}
                                fullWidth
                                type="stealth"
                                onClick={() =>
                                    triggerExport({
                                        export_format: item.format,
                                        export_context: item.resource,
                                        dashboard: item.dashboard,
                                        insight: item.insight,
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
