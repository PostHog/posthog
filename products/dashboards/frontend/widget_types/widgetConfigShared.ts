import type { SessionReplayWidgetConfig } from '../generated/widget-configs.zod'
import dateFromOptions from '../generated/widget-date-from-options.json'

export type WidgetDateFromValue = NonNullable<NonNullable<SessionReplayWidgetConfig['dateRange']>['date_from']>

export const WIDGET_DATE_RANGE_SELECT_OPTIONS = dateFromOptions.options as {
    value: WidgetDateFromValue
    label: string
}[]

export function resolveWidgetFilterTestAccounts(
    configValue: boolean | undefined | null,
    projectDefault: boolean
): boolean {
    return configValue ?? projectDefault
}
