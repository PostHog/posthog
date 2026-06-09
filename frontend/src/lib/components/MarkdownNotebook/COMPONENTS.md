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

`ViewComponent` renders the read panel.
`EditComponent` is optional; if omitted, the component only has a view panel.
Call `updateProps(partialProps)` from either component to update persisted markdown props.

`exclusiveEditPanel` hides the view panel while the edit panel is open.
Use it for expensive or stateful components that should not mount twice.

`hideModeActions` hides the view/edit toggle buttons while preserving the component toolbar and delete action.
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
<RevenueCard view edit disabled={false} metric="arr" />
```

`view` and `edit` are reserved props used by the notebook shell to persist which panels are open.
Components with visible mode actions should allow these props to round-trip.
Components with `hideModeActions` do not persist them.
`Prompt` is a special AI input tag and should not use `view` or `edit`.

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

If the node type does not exist yet, create the notebook node first under `frontend/src/scenes/notebooks/Nodes`, register it in `KNOWN_NODES`, add an icon in `NODE_ICONS`, then follow the steps above.

## Reserved tags

Do not reuse built-in markdown tags such as `Query`, `Image`, `Embed`, `Python`, or internal AI tags such as `Prompt` and `Chat`.
Choose a specific tag name that describes the persisted block.

## Testing checklist

Add or update tests for:

- parsing and serializing the tag
- rendering the view component
- editing props through `updateProps`
- slash-menu insertion when `insertCommand` is present
- validation errors when `validateProps` rejects invalid props
