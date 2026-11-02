# TaxonomicFilter call sites and blast radius

The TaxonomicFilter is used in dozens of places. Don't try to enumerate
them — they drift. Find the current set with:

```bash
rg -l '<TaxonomicFilter\b|TaxonomicPopover|TaxonomicPropertyFilter' frontend products
```

## Wrappers (touch one, affect many)

- `lib/components/TaxonomicPopover/TaxonomicPopover.tsx` — generic popover wrapper
- `lib/components/PropertyFilters/components/TaxonomicPropertyFilter.tsx` — property-filter row
- `lib/components/PropertySelect/PropertySelect.tsx` — single-property selector
- `lib/components/EventSelect/EventSelect.tsx` — single-event selector
- `lib/components/FlagSelector.tsx` — feature-flag picker
- `lib/components/QuickFilters/QuickFilterForm.tsx` — quick-filter authoring
- `lib/components/IngestionControls/triggers/EventTrigger.tsx` — capture trigger config

A change ripples through every consumer of these. Run their tests before
shipping anything broad.

Many call sites skip the wrappers and mount `TaxonomicFilter` directly, so they
always render it with no wrapper logic in front.
Examples are `ColumnConfigurator.tsx` (inline `<TaxonomicFilter>`),
`UniversalFilters.tsx` (`PureTaxonomicFilter`) and `TaxonomicBreakdownPopover.tsx`.
Search the repo for direct `<TaxonomicFilter` and `PureTaxonomicFilter` uses to
find them all before you decide which call sites a change touches.

`TaxonomicPropertyFilter` has a branch that skips the popover entirely: without
`disablePopover`, a new or empty row, or a HogQL row, sets
`showInitialSearchInline` and renders the picker inline.
With `disablePopover`, that branch is skipped and the picker always opens in a
popover.
A group row (`nestedGroup`) opens no picker at all; a leaf row inside a group
follows the same rules as any other row.

## Prop combinations to think about

| Prop                   | Why it matters                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `taxonomicGroupTypes`  | Drives which tabs appear and their order. Single-group, subset, and full-default all exist. |
| `excludedProperties`   | Hides already-selected keys; some scenes hide system-only properties this way.              |
| `metadataSource`       | Drives whether the property panel queries events / persons / sessions / warehouse.          |
| `eventNames`           | Insight-series names so per-event property promotion can run; reactive via `propsChanged`.  |
| `onChange` / `onEnter` | Both shapes exist; `onEnter` is used for HogQL expression entry without a concrete pick.    |
| `optionsFromProp`      | Some pickers inject local items instead of fetching from the API.                           |

## Smoke test before shipping a broad change

- [ ] Add an event filter inside an insight (Trends or Funnel)
- [ ] Add a property breakdown to a Trends insight
- [ ] Add a person property filter on the Persons scene
- [ ] Add a filter inside Replay's universal filter bar
- [ ] Add a cohort field condition
- [ ] Open the property selector inside Web analytics conversion goal
- [ ] If you touched tab rendering, check a call site that goes through a wrapper (such as `TaxonomicPopover`) and one that mounts `TaxonomicFilter` directly
