export const ACCOUNT_WIDGET_WEEKS = [4, 8, 12, 26] as const

export type AccountWidgetWeeks = (typeof ACCOUNT_WIDGET_WEEKS)[number]

export const DEFAULT_ACCOUNT_WIDGET_WEEKS: AccountWidgetWeeks = 8

/** Reads a saved week count, which is untyped and can be stale, and falls back to the default. */
export function getAccountWidgetWeeks(saved: string): AccountWidgetWeeks {
    return ACCOUNT_WIDGET_WEEKS.find((weeks) => String(weeks) === saved) ?? DEFAULT_ACCOUNT_WIDGET_WEEKS
}
