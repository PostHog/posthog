// @posthog/quill-components
//
// Middle layer of the quill design system: higher-level compositions of
// primitives that wire several together with sensible defaults. Think
// FormField (Label + Input + error + description slot), ConfirmDialog
// (Dialog + destructive Button + focus management), ButtonGroup with
// dropdown menu chaining, DataTable wiring sort + filter + selection on
// top of Table primitives. Opinionated wrappers you'd otherwise hand-roll
// in every app.

export { DataTable, type DataTableProps } from './data-table'
export { DateTimePicker, type DateTimePickerProps, type DateTimeValue, type DateFormatOrder } from './date-time-picker'
export { DatePicker, type DatePickerProps } from './date-picker'
export { quickRanges, CUSTOM_RANGE, type DateTimeRange, type DateTimeRangeName } from './date-time-ranges'
export { useCalendar, Day, Month, type UseCalendarOptions, type UseCalendarReturn } from './use-calendar'
// `Metric` is intentionally NOT re-exported here: it pulls `@posthog/quill-charts` (d3), and this
// barrel is inlined into the always-eager `@posthog/quill` bundle. Import it from its own entry —
// `@posthog/quill-components/metric` — so charts only loads where a metric tile is actually used.
