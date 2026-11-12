import { useActions, useMountedLogic } from 'kea'

import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel } from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'

import type { ExportButtonItem } from './ExportButton'
import { exportButtonItemAttributes } from './exportButtonItemAttributes'

export function QuillExportFileTypeItems({ items }: { items: ExportButtonItem[] }): JSX.Element {
    useMountedLogic(exportsLogic)
    const { startExport } = useActions(exportsLogic)

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>File type</DropdownMenuLabel>
            {items.map(({ title, ...triggerExportProps }, i) => {
                const { extension, target, body } = exportButtonItemAttributes(triggerExportProps)
                return (
                    <DropdownMenuItem
                        key={i}
                        onClick={() => startExport(triggerExportProps)}
                        data-attr={`export-button-${extension}`}
                        data-ph-capture-attribute-export-target={target}
                        data-ph-capture-attribute-export-body={body.length ? JSON.stringify(body) : null}
                    >
                        {title ? title : `.${extension}`}
                    </DropdownMenuItem>
                )
            })}
        </DropdownMenuGroup>
    )
}
