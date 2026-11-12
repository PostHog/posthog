import { useActions, useMountedLogic } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ExportButtonItem } from './ExportButton'
import { exportButtonItemAttributes } from './exportButtonItemAttributes'

interface QuillExportButtonProps {
    items: ExportButtonItem[]
    tooltip?: string
}

export function QuillExportButton({ items, tooltip }: QuillExportButtonProps): JSX.Element {
    useMountedLogic(exportsLogic)
    const { startExport } = useActions(exportsLogic)
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                disabled={!!disabledReason}
                render={
                    <Button
                        variant="outline"
                        tooltip={tooltip}
                        disabledReason={disabledReason}
                        data-attr="export-button"
                    />
                }
            >
                Export
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
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
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
