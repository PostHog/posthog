import { AppMetricsTab } from '~/types'

interface Description {
    successes: string
    successes_tooltip?: React.ReactNode | string

    successes_on_retry?: string
    successes_on_retry_tooltip?: React.ReactNode | string

    failures: string
    failures_tooltip?: React.ReactNode | string
}

export const DescriptionColumns: Record<string, Description> = {
    [AppMetricsTab.ProcessEvent]: {
        successes: 'Events processed',
        successes_tooltip: (
            <>
                These events were successfully processed and transformed by the <i>processEvent</i> app method.
            </>
        ),
        failures: 'Failed events',
        failures_tooltip: (
            <>
                These events had errors when being processed by the <i>processEvent</i> app method, but were still
                ingested.
            </>
        ),
    },
    [AppMetricsTab.OnEvent]: {
        successes: 'Events processed',
        successes_tooltip: (
            <>
                These events were successfully processed by the <i>onEvent</i> app method on the first try.
            </>
        ),
        successes_on_retry: 'Events processed on retry',
        successes_on_retry_tooltip: (
            <>
                These events were successfully processed by the <i>onEvent</i> app method after being retried.
            </>
        ),
        failures: 'Failed events',
        failures_tooltip: (
            <>
                These events had errors when being processed by the <i>onEvent</i> app method.
            </>
        ),
    },
    [AppMetricsTab.ComposeWebhook]: {
        successes: 'Events processed',
        successes_tooltip: (
            <>
                These events were successfully processed by the <i>composeWebhook</i> app method on the first try.
            </>
        ),
        successes_on_retry: 'Events processed on retry',
        successes_on_retry_tooltip: (
            <>
                These events were successfully processed by the <i>composeWebhook</i> app method after being retried.
            </>
        ),
        failures: 'Failed events',
        failures_tooltip: (
            <>
                These events had errors when being processed by the <i>composeWebhook</i> app method.
            </>
        ),
    },
    [AppMetricsTab.ExportEvents]: {
        successes: 'Events delivered',
        successes_tooltip: (
            <>These events were successfully delivered to the configured destination on the first try.</>
        ),
        successes_on_retry: 'Events delivered on retry',
        successes_on_retry_tooltip: (
            <>These events were successfully delivered to the configured destination after being retried.</>
        ),
        failures: 'Failed events',
        failures_tooltip: <>These events failed to be delivered to the configured destination due to errors.</>,
    },
    [AppMetricsTab.HistoricalExports]: {
        successes: 'Events delivered',
        successes_tooltip: (
            <>These events were successfully delivered to the configured destination on the first try.</>
        ),
        successes_on_retry: 'Events delivered on retry',
        successes_on_retry_tooltip: (
            <>These events were successfully delivered to the configured destination after being retried.</>
        ),
        failures: 'Failed events',
        failures_tooltip: <>These events failed to be delivered to the configured destination due to errors.</>,
    },
    [AppMetricsTab.ScheduledTask]: {
        successes: 'Successes',
        successes_tooltip: (
            <>
                How many times <i>runEveryMinute</i>, <i>runEveryHour</i> or <i>runEveryDay</i> was called successfully.
            </>
        ),
        failures: 'Failures',
        failures_tooltip: (
            <>
                How many times <i>runEveryMinute</i>, <i>runEveryHour</i> or <i>runEveryDay</i> failed due to errors.
            </>
        ),
    },
}
