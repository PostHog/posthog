import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import {
    NEW_CHECK_ACTION_ID,
    dataQualityOverviewLogic,
} from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

const SETTINGS_LABEL = 'Data quality settings'

export function CatalogTablesCheckActions(): JSX.Element {
    const { checks, startingRun, isRunning, runTarget } = useValues(dataQualityOverviewLogic)
    const { runChecks, setLastActionCheck } = useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const anyRunActive = startingRun || isRunning
    const runningAll = anyRunActive && runTarget?.kind === 'all'
    const runAllDisabledReason =
        checks.length === 0
            ? 'There are no checks to run yet'
            : anyRunActive && !runningAll
              ? 'Checks are already running'
              : undefined

    return (
        <div className="flex w-full items-center gap-2 @min-[40rem]/main-content:ml-auto @min-[40rem]/main-content:w-auto">
            <Button
                id={NEW_CHECK_ACTION_ID}
                variant="outline"
                onClick={() => {
                    setLastActionCheck(null)
                    openEditor(null, null)
                }}
                data-attr="data-catalog-tables-new-check"
            >
                <IconPlus />
                New check
            </Button>
            <Button
                variant="outline"
                onClick={() => runChecks({ kind: 'all' })}
                loading={runningAll}
                disabledReason={runAllDisabledReason}
                data-attr="data-catalog-tables-run-all"
            >
                Run all checks
            </Button>
            <Button
                size="icon"
                aria-label={SETTINGS_LABEL}
                tooltip={SETTINGS_LABEL}
                className="text-muted-foreground"
                render={<LinkPrimitive to={urls.settings('environment-data-quality')} />}
                data-attr="data-catalog-tables-settings"
            >
                <IconGear />
            </Button>
        </div>
    )
}
