# Command K search: UX spec

Source of truth for the new Command K search.
Gated by the `new-command-k-search` feature flag (`FEATURE_FLAGS.NEW_COMMAND_K_SEARCH`).
Flag off keeps the current `Search.tsx` / `searchLogic.tsx` palette untouched.
When a change disagrees with this file, change this file in the same PR or don't ship the change.

## Goals, in priority order

1. **Stable.** Rows never jump, reorder, or blink while the user types. The highlighted row never moves under the cursor.
2. **Fast.** Every keystroke paints in the same frame. Network only adds rows; it never blocks typing or removes what is already visible.
3. **Powerful.** Smart filters (`is:dashboard createdBy:me revenue`) narrow results without leaving the keyboard.
4. **Familiar.** With an empty input, the palette looks and behaves like today's: Recents, Starred, Products.

## Building blocks

- Styled only with quill tokens (`bg-card`, `bg-background`, `text-muted-foreground`, `border-input`, `ring-ring`, `fill-selected`) under a `data-quill` root, never LemonUI tokens such as `bg-surface-primary` or `text-tertiary`.
- Built from quill primitives: `InputGroup` (with `InputGroupInput`, `InputGroupAddon`, `InputGroupButton`) for the field, `Button` rows, `MenuLabel` section headers, `Skeleton`, `Kbd`, `ScrollArea`. One combobox input, one listbox, grouped options, wired with `aria-activedescendant`.
- Not on quill's `Autocomplete`: Base UI tracks the highlight by index and cannot hold it by item identity (stability rule 5), so the logic owns the highlight.
- Committed filters render inline as text, not as boxed chips: the key in the foreground color, the value in the brand color on a light tint (`is:` **Dashboard**). They still behave as chips (select, remove, edit). There is no × on a chip; ⌫ removes it.
- The field has a fixed height. Committing a chip never resizes it; chips that overflow scroll sideways.
- One kea logic (`commandKSearchLogic`) owns state, highlight, and orchestration. Components only render and translate events. The rules live in pure modules with unit tests:
  - `commandKQuery.ts`: tokenizing, cursor context, `resolveQuery` (filters, free text, and the backend search string in one pass), and which edits commit a chip.
  - `commandKKeys.ts`: what each key press means (`keyIntent`).
  - `commandKSections.ts`: section order, suggestions, and the stale/loading rules.
  - `commandKSources.ts`: every remote request in one table (query kind, sections it fills, when it applies, how it fetches).
  - `commandKFilterOptions.ts`: the values each filter key suggests.
- The lists that need no request (products, settings, create new, and the rest) come from `searchListsLogic`, shared with the current palette, so both palettes find the same things.
- The logic mounts with the palette and unmounts when it closes. That is the whole lifecycle: mounting is the "opened" event, unmounting is "abandoned" when nothing was opened, and unmounting drops every cache and cancels every request.

## Anatomy

```text
┌──────────────────────────────────────────────────────────────┐
│ 🔍 is:Dashboard revenue▍        [✨ Press Tab to ask AI] [×]   │  input + chips (+ Cancel)
├──────────────────────────────────────────────────────────────┤
│ SUGGESTIONS            (only while a filter token is active)  │
│ RESULTS / RECENTS / STARRED / PRODUCTS / ...                  │
├──────────────────────────────────────────────────────────────┤
│ ↑↓ navigate  ↵ open  ⌘↵ new tab  ⇥ complete  ⌫ remove filter Esc │  footer
└──────────────────────────────────────────────────────────────┘
```

Placeholder: `Search or ask PostHog AI… try is:dashboard`.

Input controls, carried over from the current palette:

- **Press Tab to ask AI** shows while Tab would ask AI: there is a query, no filter key, and the highlighted row is not a filter row. Clicking it does the same as Tab.
- **Clear (×)** shows whenever there is text or a chip, and clears both.
- **Cancel** closes the palette. It shows only with the `today-rail-nav` UI at narrow widths, where the footer hides, as in the current palette.

## Modes

The input is always in exactly one mode, decided from the token under the cursor.

| Mode              | Trigger                                                       | Listbox shows                                                           |
| ----------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Empty**         | Input is empty, no chips                                      | Recents, Starred, Products (today's default list)                       |
| **Key suggest**   | Cursor token is a partial filter key (`cr`, `createdB`, `is`) | Matching filter keys first, then normal results for the text            |
| **Value suggest** | Cursor token is `key:` or `key:partial`                       | Values for that key, then results already narrowed by the other filters |
| **Search**        | Cursor token is free text                                     | Results for the free text plus committed filters                        |

### Empty mode

- Sections in this fixed order: **Recents** (5), **Starred**, **Products**.
- Same data sources as today (`recentItemsModel`, `projectTreeDataLogic` shortcuts, `getTreeItemsProducts()`).
- Zero network requests on open. Everything comes from already-loaded models.
- First row is highlighted.

### Key suggest

- Typing a prefix that matches a filter key or alias shows a **Filters** section at the top.
  - `is` → `is:` "Type, such as dashboard or feature flag"
  - `createdB` → `createdBy:` "Who created it"
  - `c` → `createdBy:` (all keys starting with `c`)
- Match is case-insensitive prefix on key and aliases. Show the canonical key, not the alias.
- The Filters section holds at most 3 rows so it never pushes results far down.
- `Tab` or `↵` on a key row completes it to `key:` and switches to Value suggest. It does not navigate.
- Plain text results still render below, so typing `is` still finds an insight called "Issues".

### Value suggest

- `is:` with no value lists **every** type, grouped and alphabetized, with its icon. No network.
- `is:fe` narrows to types whose label or alias starts with `fe` (`Feature flag`). Prefix match first, then substring.
- `createdBy:` lists `me` first, then org members. `createdBy:Ca` lists members whose first name, last name, or email starts with `Ca`.
  - Results below the suggestions are already filtered to objects created by anyone matching `Ca`, so the user sees the effect before committing.
- `Tab`, `↵`, or typing a space commits the value into a chip. The cursor moves past it, ready for the next token.
- Typing the last letter of a value that names exactly one option commits it too, as if its suggestion were picked. A space typed right after (at the start, or after another space) is dropped, because it would separate nothing.
- If the value matches nothing, show one row: "No match for `Ca`. Press Space to search anyway." Free text values stay valid for `createdBy` (substring on name/email).

### Search mode

- Free text plus all committed chips go to the file system endpoint in one request. Typing a value that names exactly one option (`is:dashboard`) commits it as a chip without Space, as if its suggestion were picked.
- Sections, in this fixed order, covering everything the current palette finds:
  1. **Results**: file system objects (insights, dashboards, feature flags, experiments, surveys, notebooks, cohorts, actions, early access features, replay playlists, data pipelines).
  2. In-memory lists, filtered on every keystroke: **Products**, **Data management**, **People**, **Health**, **Misc**, **Settings** (with a Dark mode / Light mode row for "dark", "light", "theme", "appearance"), **Create new**.
  3. Remote lists that the file system does not hold: **Events**, **Properties**, **Workflows** (one unified search request), **Accounts** (behind the customer analytics flag), **Support tickets** (3+ characters or a ticket number), **Persons**, **Groups**.
  4. **Ask PostHog AI**.
- With any filter (a chip, or a valid `key:value` still being typed), only **Results** shows, because filters apply only to objects.
- PostHog AI ignores filters, so it is not offered while there is a filter key in the input (a filter, or a `key:` whose value is being typed). Neither **Press Tab to ask AI** nor the **Ask PostHog AI** row shows, and Tab does not ask AI.
- When a filtered search finds nothing, the list shows an empty state: "No results", with a **Clear search** outline button that clears the input and returns focus to it.

## Smart filters

Keys are case-insensitive. `createdby:` and `createdBy:` are the same token.
Each key holds one value. Committing `is:insight` while an `is:` chip exists replaces that chip in place. Different keys combine with **and**. There is no **or** in v1.
Prefix any token with `-` to negate it: `-is:insight`, `-createdBy:me`.
Quote values with spaces: `createdBy:"Ada Lovelace"`, `in:"Team Growth"`.

### Launch set

| Key          | Aliases                   | Values                                                                                                                                                   | Example            | Backend today                                  |
| ------------ | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------------------------------------------- |
| `is:`        | `type:`                   | Every type in `fileSystemTypes` from the product manifests (action, cohort, dashboard, experiment, feature flag, insight, notebook, survey, workflow, …) | `is:flag`          | ✅ `type:` in `file_system` search             |
| `createdBy:` | `by:`, `author:`, `user:` | `me`, org members                                                                                                                                        | `createdBy:me`     | ✅ `user:` / `author:` in `file_system` search |
| `in:`        | `path:`, `folder:`        | Project tree folders                                                                                                                                     | `in:"Growth team"` | ✅ `path:`                                     |
| `name:`      | `title:`                  | Free text, matches name only (not description)                                                                                                           | `name:revenue`     | ✅ `name:`                                     |

The backend tokenizes these in `FileSystemViewSet._apply_search_to_queryset` (`posthog/api/file_system/file_system.py`), including `-` negation and quotes.
The frontend maps friendly keys to backend keys (`is:` → `type:`, `createdBy:` → `user:`) and sends one `search` string.

### Suggested next filters

Ordered by usefulness vs. backend cost.

| Key                        | Values                                                         | Example                   | Why                                                       | Backend work                                                  |
| -------------------------- | -------------------------------------------------------------- | ------------------------- | --------------------------------------------------------- | ------------------------------------------------------------- |
| `is:starred` / `is:recent` | none                                                           | `is:starred revenue`      | Search inside my own shortlist                            | Starred = shortcuts join; recent = `order_by=-last_viewed_at` |
| `updated:` / `created:`    | `today`, `7d`, `30d`, `>2026-01-01`                            | `updated:7d is:dashboard` | "That flag I touched last week"                           | `created_at__gt` exists; `updated` needs a field              |
| `viewed:`                  | `today`, `7d`                                                  | `viewed:7d`               | Recents with a time window                                | `last_viewed_at` exists for current user                      |
| `tag:`                     | Project tags                                                   | `tag:marketing`           | Dashboards, insights, flags already have tags             | New: tags not on `FileSystem`                                 |
| `status:`                  | Per type: `active`, `inactive`, `draft`, `running`, `archived` | `is:flag status:inactive` | Stale flag cleanup, running experiments                   | New, per-type; only offer after an `is:` chip                 |
| `key:`                     | Free text                                                      | `key:checkout-v2`         | Feature flag key exact match, the most common flag lookup | `ref` / flag key lookup                                       |
| `has:`                     | `description`, `tags`, `alerts`, `subscriptions`               | `is:insight has:alerts`   | Find insights with alerts set up                          | New, per-type                                                 |
| `sort:`                    | `recent`, `name`, `created`                                    | `sort:name`               | Overrides default ranking                                 | `order_by` exists                                             |

Rule for adding a filter: it ships only when its values can be suggested (static list or a cached list). A filter the user cannot discover through autocomplete does not ship.

## Stability rules

These are the rules reviewers check. Breaking one is a bug.

1. **Fixed section order.** Sections render in the order in this doc for a given mode. A section never moves above another because its data arrived first.
2. **Reserve space while loading.** The Results section renders skeleton rows at its last known height (or 3 on its first load) while it loads. It does not collapse to zero and then expand. Sections below Results that usually come back empty (Events, Properties, Workflows, Accounts, Support tickets, Persons, Groups) reserve nothing on their first load and appear only once they have rows, so skeletons never show up just to collapse.
3. **Never blank on keystroke.** Keep the previous result set visible (dimmed slightly after 150 ms) until the new set arrives. Swap in one commit.
4. **No mid-query re-rank.** Once rows for a query string are painted, later responses for the same query append to their own section. They never reorder rows above them.
5. **Highlight follows identity, not index.** The highlighted row is tracked by item key (`section/type:ref`). Once the person moves the highlight (arrow keys or pointer), it stays on that item through result swaps while the item still exists. If it is gone, or the person never moved it, the first row is highlighted.
6. **Fixed row height.** Every row is one line, same height. Long names truncate with an ellipsis; the type label and timestamp never wrap.
7. **Instant local, deferred remote.** Local sources (recents, starred, products, filter keys, type values, cached members) filter synchronously on every keystroke. Remote search debounces at 150 ms.
8. **Latest wins.** Each remote request is aborted when a newer one starts (`AbortController`). A late response for an older query is dropped, never painted.
9. **Chips don't reflow the list.** Committing a chip changes the query but follows rules 3 to 5 like any other edit.

## Performance budget

- Keystroke to paint: under 16 ms for local filtering. Measure in the React profiler before merging.
- Remote result under 300 ms p95 for `file_system` search with filters.
- Per-section caps: Filters 3, Suggestions 8 (`is:` lists every type, since that list is short and fixed), Results 20, Recents 5, Products, Settings, Persons and Groups 5 each in Search mode. No virtualization needed at these sizes.
- Cache remote responses by normalized query string (sorted chips + trimmed text) for the life of the palette. Backspacing to an earlier query paints from cache with zero network.
- Org members for `createdBy:` and folders for `in:` load the first time that filter is used, then filter locally. Opening the palette sends no request.
- The parser and the local filters are pure and memoized on input text.

## Keyboard

| Key                     | Action                                                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `↑` / `↓`               | Move highlight. Wraps at ends. Skips section headers.                                                                 |
| `↵`                     | Filter key or value row: complete it. Result row: open it.                                                            |
| `⌘↵`                    | Open result in a new tab.                                                                                             |
| `Tab`                   | Key or value row: complete it. Other rows, with a query and no filter key: ask PostHog AI. Else focus moves as usual. |
| `Space`                 | After `key:value`, commits the chip.                                                                                  |
| `⌫` at start of text    | First press selects the previous chip. Second press removes it.                                                       |
| `↵` on a selected chip  | Turns the chip back into editable text (`is:dashboard`) with the cursor after it.                                     |
| `←` / `→` at text edges | Move between chips.                                                                                                   |
| `Esc`                   | Text in the input: clear it. Empty input: close the palette.                                                          |

## Edge cases

- **Unknown key** (`foo:bar`): treat the whole token as free text. Don't show an error.
- **Colon inside text** (`error: timeout`): a token is a filter only when the key is a known key or alias. Otherwise it is free text.
- **Pasted query** (`is:flag createdBy:me checkout`): parse into chips immediately.
- **Same key twice** (`is:dashboard is:insight`): the later value replaces the earlier chip. While a value for a key that already has a chip is being typed, results preview the new value instead of the chip.
- **Invalid value** (`is:banana`): keep it as plain text, no chip, and show "No type called banana" in the Suggestions section.
- **Ask PostHog AI**: always the last section in Search mode when there is no filter key, with the raw input text as the question.

## Out of scope for v1

- Saved searches.
- `OR` of any kind, within a key or across keys, and parentheses.
- Natural-language filter inference ("dashboards I made last week" → chips). Good v2 candidate.

## Analytics

Every step emits an event so we can see adoption and drop-off:

- `command k search opened` (source: shortcut, button)
- `command k filter suggested` / `command k filter committed` (key, value kind, via: tab, enter, space, paste)
- `command k result opened` (section, position, has_filters, filter_keys, query_length)
- `command k search abandoned` (closed with no result opened; last mode, had_filters)
- `command k no results shown` (a filtered search found nothing; filter_keys)
- `command k search cleared` (source: clear-button, escape, no-results; had_filters, filter_keys)
