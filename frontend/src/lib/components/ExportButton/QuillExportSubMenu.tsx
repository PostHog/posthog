import { useActions, useMountedLogic } from 'kea'

import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ExportButtonCopyToClipboardItem, ExportButtonItem } from './ExportButton'
import { exportButtonItemAttributes } from './exportButtonItemAttributes'

export function QuillExportSubMenu({
    items,
    copyToClipboardItems,
}: {
    items: ExportButtonItem[]
    copyToClipboardItems?: ExportButtonCopyToClipboardItem[]
}): JSX.Element {
    useMountedLogic(exportsLogic)
    const { startExport } = useActions(exportsLogic)
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)

    if (disabledReason) {
        return (
            <DropdownMenuSub>
                <DropdownMenuSubTrigger disabledReason={disabledReason} data-attr="export-button">
                    Export
                </DropdownMenuSubTrigger>
            </DropdownMenuSub>
        )
    }

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger data-attr="export-button">Export</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
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
                {copyToClipboardItems && copyToClipboardItems.length > 0 ? (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Copy to clipboard</DropdownMenuLabel>
                            {copyToClipboardItems.map((item, i) => (
                                <DropdownMenuItem
                                    key={i}
                                    onClick={item.onClick}
                                    disabledReason={item.disabledReason}
                                    data-attr={item['data-attr']}
                                >
                                    {item.title}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    </>
                ) : null}
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
