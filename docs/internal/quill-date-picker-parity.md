# Quill date picker parity: status and migration plan

Status of the LemonUI → Quill date picker migration, the remaining feature gaps, and what's left to reach full parity. Written 2026-07-09; treat file/line references as a snapshot.

## Where things stand

The migration seam is `frontend/src/lib/components/DatePicker/DatePicker.tsx`, a design-system-agnostic single-date picker gated by the `QUILL_DATE_PICKER` feature flag (`frontend/src/lib/constants.tsx`, owner `@pauldambra`). Under the flag it renders Quill's `DatePicker` in a Quill `Popover`; with the flag off it renders `LemonCalendarSelectInput`.

**The single-date gaps are closed.** The seam's Quill path now covers its full prop surface, so the old `quillCanRender` per-prop fallback is gone — the flag alone picks the renderer:

- **12-hour time entry**: Quill's `SegmentedDateInput`/`DatePicker` accept `hourCycle` (12 renders 1-12 with an AM/PM toggle); the seam maps `use24HourFormat` onto it, keeping LemonUI's 12-hour default.
- **Selection windows** (`selectionPeriod: 'past' | 'upcoming'` + `selectionPeriodTimezone`): the seam evaluates "now" as the selection timezone's wall clock (`dayjsNowInTimezone`) and hands the panel absolute datetime bounds. The panel's calendar disables by day and clamps applied datetimes to the full bounds, so a wrong-direction time on the boundary day cannot be applied.
- **Unbounded future dates**: Quill's `DatePicker` no longer caps at today when `maxDate` is omitted (calendar navigation still caps ten years out). `DateTimePicker` keeps its cap-at-now default.
- **Controlled visibility** (`visible`/`onOpen`/`onClickOutside`/`onClose`): wired through Quill `Popover`'s `open`/`onOpenChange` in the seam.
- **Week start**: the seam passes `teamLogic.weekStartDay` as `weekStartsOn`, so the team setting is respected under the flag.
- **Dropped rather than built**: hour-only granularity and single-date multi-month (`months`) had zero production callers and were removed from the seam API.

Seam adoption so far: 4 call sites (`AnnotationModal`, `BatchExportEditForm`, visual review `QuarantineAction`, `Reminders`). One production usage of the Quill range picker exists: `products/mcp_analytics/frontend/components/McpDateFilter.tsx`. antd's DatePicker is fully gone.

Known remaining single-date sharp edges (accepted for now): the segmented input's year entry is two-digit (2000–2099), and `DateTimePicker`'s start/end inputs lack the min-clamp that `DatePicker` has.

## The LemonUI surface still to replace

| Component | Direct importers | Notes |
| --- | --- | --- |
| `DateFilter` (composite) | ~50 files | Quick presets, rolling ranges, fixed range, fixed range with time, date-to-now, relative ranges, jump-to-timestamp |
| `LemonCalendarSelectInput` | 10 files | Single date trigger+popover; heaviest exotic user is `FeatureFlagSchedule` (`selectionPeriod="upcoming"` + `selectionPeriodTimezone` + dynamic granularity) |
| `LemonCalendarSelect` (direct) | 5 files | `VariableCalendar`, `SurveyEdit`, `ExperimentDuration`, internal to `DateRangePicker` and the seam |
| `LemonCalendarRange` | internal to `DateFilter` only | Range click state machine lives in `LemonCalendarRangeInline` |
| `FixedRangeWithTimePicker` | internal to `DateFilter` only | Separate hand-built range+time component reusing the bare `LemonCalendar` grid |
| `DateRangePicker` (+`WithZoom`) | logs/tracing scenes | Free-text relative expressions (`-1h`), recents history, timezone select |
| `PropertyFilterDatePicker` | property filters | Thin wrapper over `LemonCalendarSelectInput` |

Because adoption is per-call-site, the flag only protects call sites that have migrated — the table above is the burndown list. The 10 `LemonCalendarSelectInput` importers are close to a drop-in swap onto the seam. The 5 direct `LemonCalendarSelect` users embed the bare panel in their own popover; they need either a panel-only seam export or a refactor onto the seam's trigger.

## Range-side gaps (blocks `DateFilter`)

`DateTimePicker` is explicitly experimental and needs stabilization before `DateFilter`'s calendar surfaces can move:

- **No live value sync**: `value` only seeds internal state; reopening with a new prop value doesn't reset. Fine inside a popover that remounts, wrong for anything longer-lived.
- **Preset vocabulary mismatch**: `quickRanges` is a fixed list of 15 "Last N" presets keyed by name, while PostHog's `DateFilter` uses the relative-date string vocabulary (`-7d`, `mStart`, ...) with per-scene `dateOptions`. `McpDateFilter.tsx` hand-maintains a mapping table; parity needs configurable presets that accept the `dateMapping` shape.
- **No rolling/relative/jump-to-timestamp equivalents**: `RollingDateRangeFilter`, `RelativeDateRangeSelector`, and `JumpToTimestampPicker` are form widgets, not calendars — they should stay and only the calendar views (`LemonCalendarRange`, `FixedRangeWithTimePicker`) get swapped inside `DateFilter`.
- **Time entry hidden below the `lg` breakpoint** (segmented inputs only render in the wide layout), and no min-clamp on the start/end inputs.
- **Range click semantics differ** from `LemonCalendarRangeInline`'s tested re-anchoring state machine (`LemonCalendarRange.test.tsx` pins a 7-click sequence); decide whether Quill's "last-set edge" behavior is the intended replacement and update tests accordingly.

`DateRangePicker` (logs/tracing) is a separate decision: it is built around free-text relative expressions, recents, and a timezone select, and probably keeps its own UI with only the embedded `LemonCalendarSelect` popovers swapping to the seam.

## Remaining order of work

1. Roll out `QUILL_DATE_PICKER` and watch the 4 existing seam call sites.
2. Migrate the 10 `LemonCalendarSelectInput` importers onto the seam (start with `FeatureFlagSchedule` — it exercises the timezone-aware selection window hardest).
3. Add a panel-only seam export for the 5 direct `LemonCalendarSelect` users, then migrate them.
4. Remove the LemonUI renderer and the flag once all single-date call sites are on the seam.
5. Stabilize `DateTimePicker` (value sync, configurable presets, input clamp, compact time entry), then introduce a range seam inside `DateFilter` for the `FixedRange`/`FixedRangeWithTime`/`DateToNow` views.
6. Last: retire `LemonCalendar*` once `DateFilter` and `DateRangePicker` no longer reference them.
