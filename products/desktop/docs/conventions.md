# Code Conventions

These conventions expand the rules in [AGENTS.md](../AGENTS.md).

## Business Logic

Put business logic in `@posthog/core` services:

- orchestration
- retries
- request dedupe
- sagas
- derived domain decisions
- multi-source data loading

Do not put business logic in React hooks, components, stores, routers, platform adapters, or host files.

Hooks wrap one source: one query, one mutation, one subscription, or one store selector. If a hook coordinates multiple sources, move that coordination into a service method.

## Components

Use functional components and typed props.

```ts
interface AgentMessageProps {
  content: string;
}

export function AgentMessage({ content }: AgentMessageProps) {
  return (
    <Box className="py-1 pl-3">
      <MarkdownRenderer content={content} />
    </Box>
  );
}
```

Keep render functions short. Extract named components for distinct UI concerns instead of long inline conditionals.

Group component hooks by concern:

```ts
export function TaskDetail({ task: initialTask }: TaskDetailProps) {
  const taskId = initialTask.id;

  useTaskData({ taskId, initialTask });

  const workspace = useWorkspaceStore((state) => state.workspaces[taskId]);
  const [filePickerOpen, setFilePickerOpen] = useState(false);

  useHotkeys("mod+p", () => setFilePickerOpen(true), hotkeyOptions);
  useFileWatcher(effectiveRepoPath ?? null, taskId);
}
```

## Stores

Stores are state cells. Actions set state. No async, no clients, no retries, no cross-store orchestration.

Placement:

- Domain facts read by business logic: `@posthog/core`, `zustand/vanilla`.
- View state: `@posthog/ui`, `zustand`.

Separate state and actions.

```ts
interface SidebarStoreState {
  open: boolean;
  width: number;
}

interface SidebarStoreActions {
  setOpen(open: boolean): void;
  toggle(): void;
}

type SidebarStore = SidebarStoreState & SidebarStoreActions;

export const useSidebarStore = create<SidebarStore>()(
  persist(
    (set) => ({
      open: false,
      width: 256,
      setOpen: (open) => set({ open }),
      toggle: () => set((state) => ({ open: !state.open })),
    }),
    {
      name: "sidebar-storage",
      partialize: (state) => ({ open: state.open, width: state.width }),
    }
  )
);
```

Do not persist derived state. Compute counts, labels, summaries, and filtered lists from source facts.

## Hooks

Hooks are allowed for ergonomic access to one source.

```ts
export function useConnectivity() {
  const isOnline = useConnectivityStore((state) => state.isOnline);
  const check = useConnectivityStore((state) => state.check);

  return { isOnline, check };
}
```

Move multi-query logic, retry logic, and data merging to services.

## Async Cleanup

Abort before awaiting cleanup that depends on the abort signal.

```ts
// Wrong
await this.interrupt();
this.abortController.abort();

// Right
this.abortController.abort();
await this.interrupt();
```

## Imports

- Use package public exports and configured path aliases.
- Avoid deep relative imports.
- Do not create barrel files (`index.ts`).

Barrel files hide dependency edges, increase circular import risk, and make refactors harder.

## Styling

Use Tailwind first. The project uses Tailwind v4 with Radix CSS variables.

Examples:

- `text-(--gray-12)`
- `bg-(--gray-2)`
- `border-(--gray-5)`
- `rounded-(--radius-2)`
- `text-[13px]`
- `pl-[18px]`

Use inline `style` only for:

- runtime-computed values such as measured width or transform
- non-React library configuration
- CSS variables set from JS and consumed by classes

```tsx
<div
  className="bg-(--row-color)"
  style={{ "--row-color": item.color } as React.CSSProperties}
/>
```

Do not use inline `style` for static colors, spacing, layout, borders, radii, cursors, opacity, positioning, z-index, or animations when Tailwind has a utility.

When creating reusable styled components, accept both `className?: string` and `style?: React.CSSProperties`, and pass them to the underlying element.

Default line heights are set in [packages/ui/src/styles/globals.css](../packages/ui/src/styles/globals.css). Add `leading-*` only when the component needs a non-default line height. Pair arbitrary body text sizes with `leading-snug`; pair titles with `leading-tight`.

## Logging

Do not use `console.*` in source. Inject `ROOT_LOGGER` as `RootLogger`, then scope it.

```ts
constructor(@inject(ROOT_LOGGER) rootLogger: RootLogger) {
  this.log = rootLogger.scope("navigation-store");
}

this.log.info("Folder path is stale, redirecting", { folderId: folder.id });
```

Logger files are exempt from the console rule.

## Learned Hints

Use the feature settings store for progressive hints instead of ad-hoc persisted booleans.

```ts
const store = useFeatureSettingsStore.getState();

if (store.shouldShowHint("my-hint-key", 3)) {
  store.recordHintShown("my-hint-key");
  toast.info("Did you know?", "You can do X with Y.");
}

store.markHintLearned("my-hint-key");
```

The implementation lives in `packages/ui/src/features/settings/settingsStore.ts`.

## Analytics

Event definitions live in `packages/shared/src/analytics-events.ts`:

- `ANALYTICS_EVENTS`
- `EventPropertyMap`

Renderer events use `track(eventName, properties)` from `packages/ui/src/shell/analytics.ts`.

Main-process events use `trackAppEvent(eventName, properties)` from `apps/code/src/main/platform-adapters/posthog-analytics.ts`.

Both clients set `team: "posthog-code"` as a super-property.

### Event Names

- Format: `Object verbed`.
- Use Title Case only for the first word: `Task created`, `Prompt sent`.
- Use a past-tense verb: `created`, `viewed`, `sent`, `started`, `completed`, `failed`, `cancelled`.
- Spell out abbreviations: `Pull request created`, not `PR created`.
- Group by object, not feature.
- Prefer one generic event with discriminator properties over many specific events.
- Do not prefix events with `First`; first occurrence is derivable.

Good:

- `Task created`
- `Prompt sent`
- `Setup discovery completed`
- `Onboarding step completed`

Bad:

- `task_created`
- `TaskCreated`
- `created_task`
- `userClickedSendButton`
- `PR created`

### Property Names

- Use lowercase `snake_case`.
- Booleans: `is_`, `has_`, or `can_`.
- Counts: `_count`.
- Durations and sizes: include unit suffix, such as `_seconds` or `_chars`.
- IDs: `_id`.
- Enums: `_type`, `_mode`, `_source`, `_kind`, `_reason`, `_action`, or a clear noun.
- Transitions: `from_*` and `to_*`.

### Enum Values

- Use lowercase `snake_case`.
- Do not encode state as `"true"` or `"false"`.
- Use TypeScript unions for closed enums.

### Property Restrictions

Do not send:

- PII
- email addresses
- full names
- file paths
- prompt contents
- repo URLs
- large payloads
- free-form strings when an enum works

Hash values when dedupe is required.
