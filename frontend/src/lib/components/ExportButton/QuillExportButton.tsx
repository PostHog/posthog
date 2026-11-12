import { useMountedLogic } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ExportButtonItem } from './ExportButton'
import { QuillExportFileTypeItems } from './QuillExportFileTypeItems'

interface QuillExportButtonProps {
    items: ExportButtonItem[]
    tooltip?: string
}

export function QuillExportButton({ items, tooltip }: QuillExportButtonProps): JSX.Element {
    useMountedLogic(exportsLogic)
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
                <QuillExportFileTypeItems items={items} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
