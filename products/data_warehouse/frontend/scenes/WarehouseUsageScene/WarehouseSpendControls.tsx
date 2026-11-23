import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Input, Skeleton, Text } from '@posthog/quill'

import { formatBytes, formatUsd } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { warehouseUsageLogic } from './warehouseUsageLogic'

const BUDGET_HELP =
    'Budget alerts email organization admins at 50, 80 and 100 percent of the budget. They never stop queries.'
const SCAN_CAP_HELP = "The cap applies to queries run from PostHog's SQL editor only."

export function WarehouseSpendControls(): JSX.Element {
    const {
        settings,
        settingsFailed,
        budgetInput,
        scanCapInput,
        spendControlsError,
        spendControlsDirty,
        canEditSpendControls,
        isSavingSpendControls,
    } = useValues(warehouseUsageLogic)
    const { setBudgetInput, setScanCapInput, saveSpendControls, resetSpendControls, retrySettings } =
        useActions(warehouseUsageLogic)

    if (settingsFailed && !settings) {
        return (
            <WarehouseSection title="Spend controls" data-attr="warehouse-spend-controls">
                <WarehouseResourceError
                    title="Couldn't load spend controls"
                    onRetry={retrySettings}
                    data-attr="warehouse-spend-controls-retry"
                />
            </WarehouseSection>
        )
    }
    if (!settings) {
        return (
            <WarehouseSection title="Spend controls" data-attr="warehouse-spend-controls">
                <Skeleton className="h-16 w-full" />
            </WarehouseSection>
        )
    }

    if (!canEditSpendControls) {
        return (
            <WarehouseSection
                title="Spend controls"
                description="Ask an organization admin to change these."
                data-attr="warehouse-spend-controls"
            >
                <dl className="m-0 grid grid-cols-1 gap-4 @lg/warehouse-usage:grid-cols-2">
                    <div>
                        <Text size="xs" variant="muted" render={<dt />}>
                            Monthly budget
                        </Text>
                        <Text size="sm" render={<dd className="m-0" />}>
                            {settings.monthly_budget_usd === null
                                ? 'No budget'
                                : formatUsd(settings.monthly_budget_usd)}
                        </Text>
                        <Text size="xs" variant="muted">
                            {BUDGET_HELP}
                        </Text>
                    </div>
                    <div>
                        <Text size="xs" variant="muted" render={<dt />}>
                            Scan cap per query
                        </Text>
                        <Text size="sm" render={<dd className="m-0" />}>
                            {settings.max_scan_bytes_per_query === null
                                ? 'No cap'
                                : formatBytes(settings.max_scan_bytes_per_query)}
                        </Text>
                        <Text size="xs" variant="muted">
                            {SCAN_CAP_HELP}
                        </Text>
                    </div>
                </dl>
            </WarehouseSection>
        )
    }

    return (
        <WarehouseSection
            title="Spend controls"
            data-attr="warehouse-spend-controls"
            controls={
                <>
                    <Button
                        variant="link"
                        size="sm"
                        disabled={!spendControlsDirty || isSavingSpendControls}
                        onClick={() => resetSpendControls()}
                        data-attr="warehouse-spend-controls-reset"
                    >
                        Discard changes
                    </Button>
                    <Button
                        type="submit"
                        form="warehouse-spend-controls-form"
                        size="sm"
                        variant="primary"
                        loading={isSavingSpendControls}
                        disabled={!spendControlsDirty || !!spendControlsError}
                        data-attr="warehouse-spend-controls-save"
                    >
                        Save
                    </Button>
                </>
            }
        >
            <form
                id="warehouse-spend-controls-form"
                className="grid grid-cols-1 gap-4 @lg/warehouse-usage:grid-cols-2"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!isSavingSpendControls) {
                        saveSpendControls()
                    }
                }}
            >
                <Field>
                    <FieldLabel htmlFor="warehouse-monthly-budget">Monthly budget (USD)</FieldLabel>
                    <Input
                        id="warehouse-monthly-budget"
                        inputMode="decimal"
                        placeholder="No budget"
                        value={budgetInput}
                        disabled={isSavingSpendControls}
                        onChange={(event) => setBudgetInput(event.target.value)}
                        data-attr="warehouse-spend-controls-budget"
                    />
                    {spendControlsError?.field === 'budget' ? (
                        <FieldError>{spendControlsError.message}</FieldError>
                    ) : (
                        <FieldDescription>{BUDGET_HELP}</FieldDescription>
                    )}
                </Field>
                <Field>
                    <FieldLabel htmlFor="warehouse-scan-cap">Scan cap per query (GiB)</FieldLabel>
                    <Input
                        id="warehouse-scan-cap"
                        inputMode="decimal"
                        placeholder="No cap"
                        value={scanCapInput}
                        disabled={isSavingSpendControls}
                        onChange={(event) => setScanCapInput(event.target.value)}
                        data-attr="warehouse-spend-controls-scan-cap"
                    />
                    {spendControlsError?.field === 'scanCap' ? (
                        <FieldError>{spendControlsError.message}</FieldError>
                    ) : (
                        <FieldDescription>{SCAN_CAP_HELP}</FieldDescription>
                    )}
                </Field>
            </form>
        </WarehouseSection>
    )
}
