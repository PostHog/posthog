# Canvas blocks (`src/blocks/`)

Blocks are premade React components that live in the canvas source.
People drag them into a canvas in the desktop app, and the app writes them into the code: the component file goes into `src/blocks/`, and a JSX line goes where the person dropped it.
They are ordinary code. Read them, import them, and change them like any other file.

## When a canvas has blocks

The canvas has blocks when `src/blocks/runtime.tsx` exists.
Blocks that are already in the source show as JSX with a `blockId` prop, for example:

```tsx
<Metric blockId="b-mf3k2a" title="Weekly active users" event="$pageview" math="weekly_active" />
```

## Rules

1. Keep every block that is in the source, with its `blockId`, unless the person asks you to remove it.
2. To add a block yourself, import it from `./blocks/<Name>` and give it a new unique `blockId` such as `b-` plus six letters or digits. Use only blocks whose file is in `src/blocks/`. For a block that is not there, build your own component with `useCanvasFilters()`; do not write block files or `runtime.tsx` from memory.
3. All blocks share the canvas filters through `useCanvasFilters()` and `setCanvasFilters()` in `src/blocks/runtime.tsx`. When you build your own chart or number, read `useCanvasFilters()` too, so the date range and property filters apply to it.
4. A block file is yours to change. Keep its exported name and its props, because the desktop reads them to edit the block.
5. `src/blocks/library.json` records which library version each block file is a copy of. Do not edit it. While a block file is unchanged, the desktop updates it to the newest library version; after you change a file, the desktop leaves it alone.
6. Blocks call `ph.query` and `ph.state` with the user scope. Keep `inlineQueries: true` and `"user"` in `capabilities.posthog.state`.
7. An `Insight` block loads a saved insight with `ph.loadInsight`. Put each `shortId` it uses in `capabilities.posthog.insights`. The desktop adds them when a person saves, but a publish of your own must list them.

## Blocks

| Component        | Props                                                                                                                                                            |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Metric`         | `title`, `event`, `math` (`total`, `dau`, `weekly_active`, `monthly_active`), `format` (`number`, `percent`, `currency`, `duration`), `compare`, `followFilters` |
| `Trend`          | `title`, `events` (string array), `math`, `display` (`line`, `bar`, `area`), `breakdown`, `followFilters`                                                        |
| `TopList`        | `title`, `event`, `math`, `breakdown`, `limit`, `followFilters`                                                                                                  |
| `Funnel`         | `title`, `steps` (string array), `windowDays`, `followFilters`                                                                                                   |
| `Retention`      | `title`, `startEvent`, `returnEvent`, `period` (`Day`, `Week`, `Month`), `intervals`, `followFilters`                                                            |
| `Insight`        | `shortId` (a saved insight), `title` (leave it out to use the insight's name)                                                                                    |
| `Goal`           | `title`, `event`, `math`, `target`, `format`, `followFilters`                                                                                                    |
| `RecentEvents`   | `title`, `limit`, `followFilters`                                                                                                                                |
| `SqlTable`       | `title`, `query` (HogQL; put `{filters}` in the WHERE clause)                                                                                                    |
| `Filters`        | `label`                                                                                                                                                          |
| `PropertyFilter` | `property`, `label`                                                                                                                                              |
| `DateRange`      | none                                                                                                                                                             |
| `Interval`       | none                                                                                                                                                             |
| `Compare`        | none. It draws the previous period on every `Trend`, as a dashed line.                                                                                           |
| `Refresh`        | none. It reloads every block and shows when the data last loaded.                                                                                                |
| `Callout`        | `tone` (`info`, `success`, `warning`), `title`, `text`                                                                                                           |

Every data block also takes:

- `description`: a short line under the title that tells readers what to take from the block.
- `span`: `wide` or `full` makes the block take two columns or the full row of its grid.

## SQL mode

`Metric`, `Goal`, `Trend`, `TopList`, `Funnel` and `RecentEvents` also take a `sql` prop with HogQL. When `sql` is set, the block runs it instead of its builder settings. `Retention` and `Insight` have no SQL mode, and `SqlTable` takes its HogQL in `query`. Put `{filters}` in the WHERE clause so the canvas filters apply. The block reads the result by column position:

- `Metric`: one row. The first column is the value, an optional second column is the previous value.
- `Goal`: one row with the value in the first column.
- `Trend`: the first column is the x axis. Each other column is a series, named by its column name.
- `TopList`: each row is a label, then a number.
- `Funnel`: each row is a step in order, the step name, then the count.
- `RecentEvents`: each row is a time, the event, then a detail.
