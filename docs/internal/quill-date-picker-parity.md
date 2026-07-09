# Quill date picker parity: gaps and migration plan

Status of the LemonUI → Quill date picker migration, the feature gaps between the two stacks, and what to build to reach parity. Written 2026-07-09; treat file/line references as a snapshot.

## Where things stand today

The migration seam already exists. `frontend/src/lib/components/DatePicker/DatePicker.tsx` is a design-system-agnostic single-date picker gated by the `QUILL_DATE_PICKER` feature flag (`frontend/src/lib/constants.tsx`, owner `@pauldambra`). Under the flag it renders Quill's `DatePicker` in a Quill `Popover`; otherwise (or whenever the caller needs a capability Quill lacks) it falls back to `LemonCalendarSelectInput`. `quillCanRender()` in that file is the authoritative list of remaining gaps: hour-only granularity, 12-hour time entry, `selectionPeriod`, multi-month, and controlled visibility all force the LemonUI fallback.

- Seam adoption so far: 4 call sites (`AnnotationModal`, `BatchExportEditForm`, visual review `QuarantineAction`, `Reminders`), all simple enough to hit the Quill path.
- Quill side: `DatePicker` (single date, the stated `LemonCalendarSelect` replacement) and `DateTimePicker` (range, still marked experimental in its own Storybook) in `packages/quill/packages/components/src/`, sharing `calendar-grid.tsx`, `segmented-date-input.tsx`, and the headless `useCalendar` hook. One production usage of the range picker exists: `products/mcp_analytics/frontend/components/McpDateFilter.tsx`.
- antd's DatePicker is fully gone; no need to account for it.

## The LemonUI surface to replace

| Component | Direct importers | Notes |
| --- | --- | --- |
| `DateFilter` (composite) | ~50 files | Quick presets, rolling ranges, fixed range, fixed range with time, date-to-now, relative ranges, jump-to-timestamp |
| `LemonCalendarSelectInput` | 10 files | Single date trigger+popover; heaviest exotic user is `FeatureFlagSchedule` (`selectionPeriod="upcoming"` + `selectionPeriodTimezone` + dynamic granularity) |
| `LemonCalendarSelect` (direct) | 5 files | `VariableCalendar`, `SurveyEdit`, `ExperimentDuration`, internal to `DateRangePicker` and the seam |
| `LemonCalendarRange` | internal to `DateFilter` only | Range click state machine lives in `LemonCalendarRangeInline` |
| `FixedRangeWithTimePicker` | internal to `DateFilter` only | Separate hand-built range+time component reusing the bare `LemonCalendar` grid |
| `DateRangePicker` (+`WithZoom`) | logs/tracing scenes | Free-text relative expressions (`-1h`), recents history, timezone select |
| `PropertyFilterDatePicker` | property filters | Thin wrapper over `LemonCalendarSelectInput` |

## Single-date gaps (each one removes a `quillCanRender` fallback)

1. **12-hour AM/PM time entry.** Quill's `SegmentedDateInput` is 24-hour only, hour+minute (no seconds, no AM/PM). LemonUI defaults to 12-hour. Note the seam currently only falls back on an *explicit* `use24HourFormat={false}`; callers that leave it unset silently get 24-hour entry under the flag where LemonUI would have shown 12-hour. Biggest single build item.
2. **Relative selection windows (`selectionPeriod: 'past' | 'upcoming'`).** Quill only has absolute, day-granular `minDate`/`maxDate`; LemonUI disables both dates *and individual time cells* relative to "now", optionally evaluated in a caller-supplied IANA timezone (`selectionPeriodTimezone`, used by feature flag schedules and covered by 4 timezone-boundary unit tests). Quill has zero timezone handling (naive local `Date` + date-fns). Recommended shape: give Quill datetime-granular `minDate`/`maxDate` enforcement (calendar + time segments), and compute those bounds in the seam from `selectionPeriod` + timezone using `lib/dayjs`, keeping tz logic out of Quill.
3. **Controlled visibility** (`visible`/`onOpen`/`onClickOutside`/`onClose`). No Quill panel work needed: implement in the seam via Quill `Popover`'s `open`/`onOpenChange`.
4. **Week start day is silently dropped.** `LemonCalendar` defaults `weekStartDay` from `teamLogic`; Quill `DatePicker` accepts `weekStartsOn` but the seam never passes it, so the team setting is ignored under the flag. Quick fix, do it first.
5. **`maxDate` default mismatch.** Quill caps at today when `maxDate` is omitted; LemonUI is unbounded above. Any future-date caller migrating onto the seam must pass `maxDate` or Quill needs an explicit "unbounded" mode.
6. **Segmented input year is two-digit, hardcoded to 2000–2099**, and typed values below `minDate` are clamped in `DatePicker` but not in `DateTimePicker`.
7. **Hour-only granularity** — zero product call sites (stories/tests only). Recommend dropping from the seam API instead of building it in Quill.
8. **Multi-month (`months`)** for single-date — no product caller sets it. Recommend dropping likewise (the range picker's dual-calendar covers the real need).

Behavior contracts to preserve when closing these: `LemonCalendarSelect.test.tsx` (timezone boundaries, past/upcoming gating, 24h semantics), `DatePicker.test.tsx` (fallback matrix, trigger style mapping, clear parity).

## Range-side gaps (the bigger lift, blocks `DateFilter`)

`DateTimePicker` is explicitly experimental and needs stabilization before `DateFilter`'s calendar surfaces can move:

- **No live value sync**: `value` only seeds internal state; reopening with a new prop value doesn't reset. Fine inside a popover that remounts, wrong for anything longer-lived.
- **Preset vocabulary mismatch**: `quickRanges` is a fixed list of 15 "Last N" presets keyed by name, while PostHog's `DateFilter` uses the relative-date string vocabulary (`-7d`, `mStart`, ...) with per-scene `dateOptions`. `McpDateFilter.tsx` hand-maintains a mapping table; parity needs configurable presets that accept the `dateMapping` shape.
- **No rolling/relative/jump-to-timestamp equivalents**: `RollingDateRangeFilter`, `RelativeDateRangeSelector`, and `JumpToTimestampPicker` are form widgets, not calendars — they should stay and only the calendar views (`LemonCalendarRange`, `FixedRangeWithTimePicker`) get swapped inside `DateFilter`.
- **Time entry hidden below the `lg` breakpoint** (segmented inputs only render in the wide layout), and the `minDate` clamp on typed input exists in `DatePicker` but not `DateTimePicker`'s start/end handlers.
- **Range click semantics differ** from `LemonCalendarRangeInline`'s tested re-anchoring state machine (`LemonCalendarRange.test.tsx` pins a 7-click sequence); decide whether Quill's "last-set edge" behavior is the intended replacement and update tests accordingly.

`DateRangePicker` (logs/tracing) is a separate decision: it is built around free-text relative expressions, recents, and a timezone select, and probably keeps its own UI with only the embedded `LemonCalendarSelect` popovers swapping to the seam.

## Suggested order of work

1. Wire `teamLogic.weekStartDay` → `weekStartsOn` in the seam (bug-level gap).
2. 12-hour AM/PM support in `SegmentedDateInput` + `DatePicker` (`use24HourFormat` equivalent); decide the default-format story for callers that never set the prop.
3. Datetime-granular min/max in Quill + seam-computed `selectionPeriod`/timezone bounds; migrate `FeatureFlagSchedule` as the proving caller.
4. Controlled visibility in the seam via `Popover` `open`/`onOpenChange`.
5. Drop `granularity="hour"` and single-date `months` from the seam API; fix or widen the year segment.
6. Migrate the remaining `LemonCalendarSelectInput` (10) and direct `LemonCalendarSelect` (5) call sites onto the seam; delete the LemonUI fallback and the flag once the fallback conditions are empty.
7. Stabilize `DateTimePicker` (value sync, configurable presets, input clamp, compact time entry), then introduce a range seam inside `DateFilter` for the `FixedRange`/`FixedRangeWithTime`/`DateToNow` views.
8. Last: retire `LemonCalendar*` once `DateFilter` and `DateRangePicker` no longer reference them.
