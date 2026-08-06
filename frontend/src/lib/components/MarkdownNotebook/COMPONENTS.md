# Markdown notebook components

Markdown notebooks store interactive blocks as JSX-like tags inside markdown:

```md
<RevenueCard metric="arr" />
```

The parser turns that tag into a `NotebookComponentBlockNode`.
Rendering, editing, validation, default props, and optional slash-menu insertion all go through `NotebookComponentDefinition`.

## Component definition API

Use the shared registry helpers from `lib/components/MarkdownNotebook`:

```tsx
import {
    MarkdownNotebook,
    createMarkdownNotebookRegistry,
    getMarkdownNotebookDefaultRegistry,
    mergeMarkdownNotebookRegistries,
    type NotebookComponentRenderProps,
} from 'lib/components/MarkdownNotebook'

function RevenueCard({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const metric = typeof node.props.metric === 'string' ? node.props.metric : 'arr'

    return (
        <button onClick={() => updateProps({ metric: metric === 'arr' ? 'mrr' : 'arr' })}>
            {metric.toUpperCase()}
        </button>
    )
}

const revenueRegistry = createMarkdownNotebookRegistry([
    {
        tagName: 'RevenueCard',
        label: 'Revenue card',
        category: 'Data',
        description: 'Revenue summary',
        aliases: ['arr', 'mrr'],
        defaultProps: { metric: 'arr' },
        getTitle: ({ props }) => `Revenue: ${String(props.metric ?? 'arr').toUpperCase()}`,
        insertCommand: {
            aliases: ['arr', 'mrr'],
        },
        ViewComponent: RevenueCard,
        EditComponent: RevenueCard,
    },
])

const registry = mergeMarkdownNotebookRegistries(getMarkdownNotebookDefaultRegistry(), revenueRegistry)

export function Notebook(): JSX.Element {
    return <MarkdownNotebook value="<RevenueCard metric=\"arr\" />" registry={registry} />
}
```

`tagName` is the persisted markdown tag.
Keep it stable after release; renaming it is a content migration.

`label`, `category`, `description`, `aliases`, and `icon` describe the component in notebook UI.
Use Sentence casing for labels.

`defaultProps` is used when the component is inserted without explicit props.
It can be a plain object or a function that returns a new object.

`insertCommand` opts the component into the slash menu.
If it is omitted, the component can still render from markdown but does not appear in `/`.
`insertCommand.defaultProps` can override the component defaults for slash insertion.

`validateProps` returns user-facing validation errors.
The notebook shell renders those above the component.

`getTitle(node)` returns a computed contextual title — a compact summary such as a URL, insight name, code title, or cached AI answer summary.
If omitted, the shell falls back to string props such as `title`, `name`, `url`, `href`, `src`, or `id`.

Every component also has a generic, user-editable title backed by the `title` prop.
In edit mode the shell renders an editable title field in the toolbar, watermarked with the `getTitle` value (or "Add a title").
In view mode the shell shows the user's title if set, otherwise the `getTitle` value.
A `title` equal to the component's own label (e.g. code blocks default `title` to "Python") is treated as no user title, so the field reads as empty by default.

`ViewComponent` renders the read panel.
`EditComponent` is optional; if omitted, the component only has a view panel.
Call `updateProps(partialProps)` from either component to update persisted markdown props.

`exclusiveEditPanel` hides the view panel while the edit panel is open.
Use it for expensive or stateful components that should not mount twice.

`hideModeActions` hides the filters/results toggle buttons while preserving the component toolbar and delete action.
Use it for components with a single meaningful display mode.

## Prop rules

Props must be serializable `NotebookPropValue`s:

- `string`
- `number`
- `boolean`
- `null`
- arrays of serializable values
- objects with serializable values

Do not put functions, dates, class instances, React nodes, or cyclic objects in props.

String props serialize as attributes:

```md
<RevenueCard metric="arr" />
```

Object and array props serialize with JSX-like expression syntax:

```md
<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />
```

Boolean `true` props serialize as bare JSX props.
Boolean `false` props stay explicit:

```md
<RevenueCard hideFilters disabled={false} metric="arr" />
```

`hideFilters` and `hideResults` are reserved props used by the notebook shell to persist which panels are hidden.
When a panel is shown, omit its prop.
Components with visible mode actions should allow these props to round-trip.
Components with `hideModeActions` do not persist them.
`Prompt` is a special AI input tag and should not use `hideFilters` or `hideResults`.

## Adding a standalone component

Use a standalone component when the block does not need the legacy notebook node runtime.

1. Create a `NotebookComponentDefinition`.
2. Add `insertCommand` if it should appear in `/`.
3. Pass a registry to `<MarkdownNotebook />`.
4. Add parser/serializer and editor tests in `MarkdownNotebook.test.ts`.

For app-specific registries, merge with `getMarkdownNotebookDefaultRegistry()`.
For replacement behavior, pass a registry directly.

## Adding a real notebook node

Markdown notebook V2 can wrap existing notebook nodes so they persist as markdown tags but render through the existing node implementation.
This adapter lives in `frontend/src/scenes/notebooks/Notebook/MarkdownNotebookV2Renderer.tsx`.

If the node type already exists:

1. Import its node module near the other `../Nodes/NotebookNode*` imports so it registers with `KNOWN_NODES`.
2. Add a tag mapping in `MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE`.
3. Add an entry to `MARKDOWN_NODE_DEFINITIONS`.
4. Add `insertCommand` on that entry if the node should appear in `/`.

Example:

```tsx
const MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE: Partial<Record<string, NotebookNodeType>> = {
  RevenueReport: NotebookNodeType.RevenueReport,
}

const MARKDOWN_NODE_DEFINITIONS = [
  {
    tagName: 'RevenueReport',
    category: 'Data',
    label: 'Revenue report',
    exclusiveEditPanel: true,
    insertCommand: {
      aliases: ['revenue', 'arr', 'mrr'],
    },
  },
]
```

The V2 adapter supplies:

- `ViewComponent`
- `EditComponent`
- `defaultProps`
- icon from `NODE_ICONS`
- title fallback from `KNOWN_NODES[nodeType].titlePlaceholder`
- toolbar title from `title`, URL-ish props, code/query summaries, or the node's serialized text

If the node type does not exist yet, create the notebook node first under `frontend/src/scenes/notebooks/Nodes`, register it in `KNOWN_NODES`, add an icon in `NODE_ICONS`, then follow the steps above.

## Reserved tags

Do not reuse the tags of the default registry (`registry.tsx`): `Query`, `Image`, `Divider`, `Embed`, `Latex`, `Python`, `DuckSQL`, `HogQLSQL`, `RecordingPlaylist`, `FeatureFlag`, `Experiment`, `Survey`, `Person`, `Group`, `Cohort`, `Map`.
The internal AI tag `Prompt` is also reserved (registered by the notebooks scene).
`Image` and `Divider` are special: they serialize back to plain markdown (`![alt](src)` and `---`) rather than component-tag syntax.
`Comment` is special too: its authorial-note flavor (`text` prop) serializes as a markdown `<!-- … -->` comment, while its discussion flavor (`ref` + `replies` props, a Google Docs-style thread anchored to an inline `<ref id="…">` highlight) serializes as a regular `<Comment … />` tag.
The lowercase inline tags `<ref>` and `<mention>` are part of the inline grammar, not components — component tags must start with an uppercase letter.
Code carries no inline marks, so a comment anchored to a selection inside a code block stores its anchor as a `ref=<id>:<start>-<end>` token in the fence info string (e.g. ` ```python ref=abc123:4-17 `), with UTF-16 offsets into the code text.
Choose a specific tag name that describes the persisted block.

## Testing checklist

Add or update tests for:

- parsing and serializing the tag
- rendering the view component
- editable toolbar title (edit-mode field, view-mode display, `getTitle` watermark)
- editing props through `updateProps`
- slash-menu insertion when `insertCommand` is present
- validation errors when `validateProps` rejects invalid props
