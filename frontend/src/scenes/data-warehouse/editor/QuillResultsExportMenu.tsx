import { useMountedLogic } from 'kea'

import { IconChevronDown, IconCopy, IconDownload } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ExporterFormat, type ExportContext } from '~/types'

import { RESULTS_COPY_FORMATS, copyResults } from './outputPaneCopy'

/**
 * One menu for getting results out: download a file, or copy the rows as text. The Lemon pane
 * splits these into a copy button and an export button; 15% of editor users export each month.
 */
export function QuillResultsExportMenu({
    response,
    rows,
    exportContext,
}: {
    response: HogQLQueryResponse | undefined
    rows: Record<string, any>[]
    exportContext: ExportContext | undefined
}): JSX.Element {
    useMountedLogic(exportsLogic)
    // Copying or exporting results requires editor access to the export resource.
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor) ?? undefined
    const noResultsReason = !response?.columns || !rows.length ? 'No results to export' : undefined

    const download = (format: ExporterFormat.CSV | ExporterFormat.XLSX): void => {
        if (exportContext) {
            exportsLogic.actions.startExport({ export_format: format, export_context: exportContext })
        }
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        disabledReason={noResultsReason ?? accessDisabledReason}
                        id="sql-editor-export"
                        data-attr="export-button"
                    />
                }
            >
                <IconDownload />
                <span className="@max-[36rem]/sql-output:hidden">Export</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {exportContext ? (
                    <>
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Download</DropdownMenuLabel>
                            <DropdownMenuItem
                                onClick={() => download(ExporterFormat.CSV)}
                                data-attr="export-button-csv"
                            >
                                <IconDownload />
                                CSV
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                onClick={() => download(ExporterFormat.XLSX)}
                                data-attr="export-button-xlsx"
                            >
                                <IconDownload />
                                Excel
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                    </>
                ) : null}
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Copy to clipboard</DropdownMenuLabel>
                    {Object.entries(RESULTS_COPY_FORMATS).map(([format, { label }]) => (
                        <DropdownMenuItem
                            key={format}
                            onClick={() => copyResults(format as keyof typeof RESULTS_COPY_FORMATS, response, rows)}
                            data-attr={`sql-editor-copy-${format}`}
                        >
                            <IconCopy />
                            {label}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
