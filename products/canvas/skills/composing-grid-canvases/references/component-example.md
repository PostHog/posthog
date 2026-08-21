# A known-good component

This is a complete, buildable component project — the welcome checklist PostHog seeds onto new home canvases (`products/canvas/backend/welcome.py`, verified against the real canvas builder).
The envelope below shows the fields you author; its `index.html` and `dependencies` come from `canvas-source-retrieve` and are kept exactly as returned (see [validating-and-publishing-canvases](../../validating-and-publishing-canvases/SKILL.md)) — the placeholders below stand in for them.
Start from it when building a checklist, settings, or any state-carrying widget, and keep its structure even when you replace the content: the project envelope, the placement contract, the capability declarations, and the defensive `ph.state` access are the parts that break when improvised.

## The project envelope

```json
{
  "schemaVersion": 1,
  "entryHtml": "index.html",
  "files": {
    "index.html": "<synthetic shell from canvas-source-retrieve — loads /src/canvas.tsx as a module>",
    "src/canvas.tsx": "<the component below>"
  },
  "dependencies": {
    "react": "<pinned>",
    "react-dom": "<pinned>",
    "@posthog/quill": "<pinned>",
    "lucide-react": "<pinned>"
  },
  "capabilities": {
    "posthog": { "insights": [], "inlineQueries": false, "captureEvents": [], "state": ["user"], "actions": [] },
    "network": { "origins": [] }
  },
  "component": { "size": { "defaultW": 3, "defaultH": 5, "minW": 2, "minH": 3 } }
}
```

- `index.html` must load `/src/canvas.tsx` as a module and every imported package must be in `dependencies` — the retrieved shell and dependency map already satisfy both. Improvising a comment-only entry fails the build with `no_entry_module`; dropping the `@posthog/quill` or `lucide-react` entries fails it with `import_not_declared`.
- Declare the full `capabilities.posthog` shape (`insights`, `inlineQueries`, `captureEvents`, `state`, `actions`) even when a field is empty, as this example does — the build freezes the declared capabilities into the artifact manifest, which older clients read expecting every field. `insights`, `inlineQueries`, and `captureEvents` are also required by the API: a partial `posthog` object is rejected with a 400 before source validation runs. Populate only what the code calls and leave the rest empty.
- `capabilities.posthog.state` must name every scope the code passes to `ph.state.*` — validation rejects an undeclared scope.
- `component.size` is in grid units and advisory; the component still has to render at any size the user drags.

## The component (`src/canvas.tsx`)

```tsx
import { useEffect, useState } from 'react'
import { Checkbox, SkeletonText, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'
import { Info } from 'lucide-react'

const ITEMS = [
  { id: 'download-desktop', label: 'Download PostHog Desktop', hint: null },
  {
    id: 'add-widget',
    label: 'Add a widget to this canvas',
    hint: 'Select Edit in the top right, then click and drag anywhere on the dotted grid and describe what should go there.',
  },
  {
    id: 'start-task',
    label: 'Start your first task',
    hint: 'Open a space and tell the agent what you want done. It picks the task up and reports back.',
  },
]

// Persistence needs both the SDK surface and a host that answers it. An old
// runtime without ph.state must degrade to session-only ticks, never crash
// the tile.
const stateApi = typeof ph !== 'undefined' && ph.state && typeof ph.state.get === 'function' ? ph.state : null

export default function WelcomeChecklist() {
  const [checked, setChecked] = useState(null)

  useEffect(() => {
    let cancelled = false
    if (!stateApi) {
      setChecked({ 'download-desktop': true })
    } else {
      stateApi
        .get('checked', { scope: 'user' })
        .then((value) => {
          if (!cancelled) {
            setChecked(value && typeof value === 'object' ? value : {})
          }
        })
        .catch(() => {
          if (!cancelled) {
            setChecked({})
          }
        })
    }
    return () => {
      cancelled = true
    }
  }, [])

  const toggle = (id, value) => {
    if (!checked) {
      return
    }
    const next = { ...checked, [id]: value }
    setChecked(next)
    if (stateApi) {
      stateApi.set('checked', next, { scope: 'user' }).catch(() => {})
    }
  }

  const done = checked ? ITEMS.filter((item) => checked[item.id]).length : 0

  return (
    // The component root must resolve height against its placement iframe viewport.
    <div className="flex h-screen flex-col gap-2 overflow-y-auto p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Text weight="medium">Welcome to PostHog</Text>
        {checked ? (
          <Text size="sm" className="text-muted-foreground">
            {done} of {ITEMS.length} done
          </Text>
        ) : null}
      </div>
      {checked === null ? (
        <SkeletonText lines={5} className="text-sm" />
      ) : (
        <div className="flex flex-col gap-1.5">
          {ITEMS.map((item) => (
            <div key={item.id} className="flex items-center gap-2">
              <Checkbox checked={!!checked[item.id]} onCheckedChange={(value) => toggle(item.id, value === true)} />
              <Text size="sm" className={checked[item.id] ? 'text-muted-foreground line-through' : ''}>
                {item.label}
              </Text>
              {item.hint ? (
                <Tooltip>
                  <TooltipTrigger render={<Info size={13} className="shrink-0 text-muted-foreground" />} />
                  <TooltipContent>
                    <div className="max-w-60">{item.hint}</div>
                  </TooltipContent>
                </Tooltip>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

## The rules the example encodes

- One file, one `export default` React component, no props, no `createRoot` — the host mounts it.
- Imports only from the platform allowlist (`react`, `@posthog/quill`, `lucide-react`, `recharts`, `dayjs`).
- `ph` is a host-injected global — never import it, and feature-detect optional surfaces like `ph.state` so the widget degrades instead of crashing on an older runtime.
- Loading state renders a skeleton, never a blank; every async access has a `.catch` that lands in a renderable state.
- Fill the placement iframe viewport (`h-screen`) and let content scroll; `h-full` cannot resolve
  on the root because the published artifact shell has no explicit height.
