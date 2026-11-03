import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

export function CatalogTablesMoreActions(): JSX.Element {
    const { checks, startingRun, isRunning } = useValues(dataQualityOverviewLogic)
    const { runChecks, setLastActionCheck } = useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const runAllDisabledReason =
        checks.length === 0 ? 'There are no checks to run yet' : startingRun || isRunning ? 'Checks are running' : null

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label="More actions"
                        className="text-muted-foreground"
                        data-attr="data-catalog-tables-more"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem
                    onClick={() => {
                        setLastActionCheck(null)
                        openEditor(null, null)
                    }}
                    data-attr="data-catalog-tables-new-check"
                >
                    New check
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => runChecks({ kind: 'all' })}
                    disabledReason={runAllDisabledReason}
                    data-attr="data-catalog-tables-run-all"
                >
                    Run all checks
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.settings('environment-data-quality'))}
                    data-attr="data-catalog-tables-settings"
                >
                    Data quality settings
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
