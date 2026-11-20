import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    Skeleton,
    Text,
} from '@posthog/quill'

import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { warehouseUsageLogic } from './warehouseUsageLogic'

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

    let body: JSX.Element
    if (settingsFailed && !settings) {
        body = (
            <WarehouseResourceError
                title="Couldn't load spend controls"
                onRetry={retrySettings}
                data-attr="warehouse-spend-controls-retry"
            />
        )
    } else if (!settings) {
        body = <Skeleton className="h-24 w-full" />
    } else {
        const readOnly = !canEditSpendControls
        body = (
            <form
                className="flex flex-col gap-4"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!isSavingSpendControls) {
                        saveSpendControls()
                    }
                }}
            >
                <div className="grid grid-cols-1 gap-4 @lg/warehouse-usage:grid-cols-2">
                    <Field>
                        <FieldLabel htmlFor="warehouse-monthly-budget">Monthly budget (USD)</FieldLabel>
                        <Input
                            id="warehouse-monthly-budget"
                            inputMode="decimal"
                            placeholder="No budget"
                            value={budgetInput}
                            disabled={readOnly || isSavingSpendControls}
                            onChange={(event) => setBudgetInput(event.target.value)}
                            data-attr="warehouse-spend-controls-budget"
                        />
                        {spendControlsError?.field === 'budget' ? (
                            <FieldError>{spendControlsError.message}</FieldError>
                        ) : (
                            <FieldDescription>
                                Budget alerts email organization admins at 50, 80 and 100 percent of the budget. They
                                never stop queries.
                            </FieldDescription>
                        )}
                    </Field>
                    <Field>
                        <FieldLabel htmlFor="warehouse-scan-cap">Scan cap per query (GiB)</FieldLabel>
                        <Input
                            id="warehouse-scan-cap"
                            inputMode="decimal"
                            placeholder="No cap"
                            value={scanCapInput}
                            disabled={readOnly || isSavingSpendControls}
                            onChange={(event) => setScanCapInput(event.target.value)}
                            data-attr="warehouse-spend-controls-scan-cap"
                        />
                        {spendControlsError?.field === 'scanCap' ? (
                            <FieldError>{spendControlsError.message}</FieldError>
                        ) : (
                            <FieldDescription>
                                The cap applies to queries run from PostHog's SQL editor only.
                            </FieldDescription>
                        )}
                    </Field>
                </div>
                {readOnly ? (
                    <Text size="sm" variant="muted">
                        Ask an organization admin to change these.
                    </Text>
                ) : (
                    <div className="flex flex-wrap gap-2">
                        <Button
                            type="submit"
                            variant="primary"
                            loading={isSavingSpendControls}
                            disabled={!spendControlsDirty || !!spendControlsError}
                            data-attr="warehouse-spend-controls-save"
                        >
                            Save
                        </Button>
                        <Button
                            type="button"
                            disabled={!spendControlsDirty || isSavingSpendControls}
                            onClick={() => resetSpendControls()}
                            data-attr="warehouse-spend-controls-reset"
                        >
                            Discard changes
                        </Button>
                    </div>
                )}
            </form>
        )
    }

    return (
        <Card data-attr="warehouse-spend-controls">
            <CardHeader>
                <CardTitle>Spend controls</CardTitle>
            </CardHeader>
            <CardContent>{body}</CardContent>
        </Card>
    )
}
