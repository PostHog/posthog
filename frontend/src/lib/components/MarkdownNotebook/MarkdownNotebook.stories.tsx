import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MarkdownNotebook, MarkdownNotebookProps } from './MarkdownNotebook'
import { NotebookCollaborationConflict } from './types'

const textNotebook = `# Weekly activation review

Activation improved after the onboarding changes. **Signup completion** is up, *workspace setup* is steady, and <u>invite acceptance</u> needs a follow-up.

- Review activation trend
- Check enterprise onboarding recordings
- Add notes for the growth sync

> Key takeaways from the growth sync:
> - Activation is trending up
> - Onboarding drop-off needs a deeper look

\`\`\`
SELECT properties.$browser AS browser, count() AS pageview_count
FROM events
WHERE event = '$pageview' AND timestamp > now() - INTERVAL 7 DAY AND properties.$browser IS NOT NULL
GROUP BY browser

ORDER BY pageview_count DESC
\`\`\`

[Open dashboard](/dashboard/123)`

const queryNotebook = `# Product analytics

<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[{"kind":"EventsNode","event":"$pageview","name":"Pageview"}]}}} />

The chart should stay editable as a notebook component while the surrounding text remains markdown-backed.`

const componentCatalogNotebook = `# Component catalog

<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} />

<Python title="Python" code="print('hello')" />

<DuckSQL title="SQL (DuckDB)" code="select * from events" returnVariable="duck_df" />

<RecordingPlaylist title="Session recordings" />

<FeatureFlag id="new-onboarding" />

<Experiment id="checkout-copy-test" />

<Person id="user-123" />

<Group type="organization" key="posthog" />

<LLMTrace id="trace-123" />`

const embedsNotebook = `# Embeds

![PostHog engineering](https://res.cloudinary.com/dmukukwp6/image/upload/data_warehouse_2c3928e9ad)

<Embed src="${window.location.origin}/mock-page.html" title="PostHog demo page" />

<Latex content="E=mc^2" />`

const mermaidNotebook = `# Release flow

A \`\`\`mermaid\`\`\` fence renders as a diagram in view mode while the source stays editable.

\`\`\`mermaid
flowchart LR
    A[Start] --> B{Tests pass?}
    B -->|Yes| C[Ship it]
    B -->|No| D[Fix it]
    D --> A
\`\`\``

const wideMermaidNotebook = `# Wide diagram

A diagram wider than the notebook column keeps its natural size and scrolls horizontally instead of shrinking.

\`\`\`mermaid
flowchart LR
    A[Signup form submitted] --> B[Validate email domain] --> C[Create organization] --> D[Provision default project] --> E[Send verification email] --> F[Track activation event] --> G[Redirect to onboarding] --> H[Show product tour]
\`\`\``

const invalidMermaidNotebook = `# Broken diagram

Invalid mermaid falls back to the plain source instead of crashing.

\`\`\`mermaid
flowchart LR
    A --> B -->
    this is not valid mermaid ]]]
\`\`\``

const malformedNotebook = `# Broken input

<Query query={{"kind":`

const invalidPropsNotebook = `# Invalid props

<Query />`

type StoryArgs = MarkdownNotebookProps

const meta: Meta<StoryArgs> = {
    title: 'Components/Markdown notebook',
    component: MarkdownNotebook,
    tags: ['autodocs'],
    args: {
        showDebug: true,
        onInteractionStateChange: () => {},
    },
    render: (props) => <ControlledNotebook {...props} />,
}

export default meta

type Story = StoryObj<StoryArgs>

function ControlledNotebook(props: MarkdownNotebookProps): JSX.Element {
    const [value, setValue] = useState(props.value)
    return <MarkdownNotebook {...props} value={value} onChange={setValue} onAskAI={props.onAskAI ?? (() => {})} />
}

function CollaborationNotebook(props: MarkdownNotebookProps): JSX.Element {
    const [value, setValue] = useState(props.value)
    const [remoteValue, setRemoteValue] = useState<string | undefined>(undefined)
    const [conflicts, setConflicts] = useState<NotebookCollaborationConflict[]>([])

    return (
        <div className="deprecated-space-y-3">
            <div className="flex gap-2">
                <LemonButton
                    size="small"
                    onClick={() =>
                        setRemoteValue(`${textNotebook}

Remote editor added a new follow-up below the checklist.`)
                    }
                >
                    Apply remote text edit
                </LemonButton>
                <LemonButton
                    size="small"
                    onClick={() =>
                        setRemoteValue(`# Weekly activation review

Remote editor rewrote the opening paragraph.

${queryNotebook}`)
                    }
                >
                    Apply conflicting edit
                </LemonButton>
            </div>
            <MarkdownNotebook
                {...props}
                value={value}
                remoteValue={remoteValue}
                onChange={setValue}
                onAskAI={props.onAskAI ?? (() => {})}
                onConflict={setConflicts}
            />
            {conflicts.length ? (
                <div className="border rounded p-2">
                    {conflicts.map((conflict) => (
                        <div key={conflict.nodeId}>{conflict.reason}</div>
                    ))}
                </div>
            ) : null}
        </div>
    )
}

export const EmptyNotebook: Story = {
    args: {
        value: '',
    },
}

export const TextOnlyNotebook: Story = {
    args: {
        value: textNotebook,
    },
}

export const HeadingsAndInlineFormatting: Story = {
    args: {
        value: `# Heading 1

## Heading 2

### Heading 3

Normal text with **bold**, *italic*, <u>underline</u>, ~~strikethrough~~, \`code\`, and [a link](https://posthog.com).

---

Text below a divider.`,
    },
}

export const ListsAndLinks: Story = {
    args: {
        value: `1. First priority
2. Second priority
3. Third priority

- Product analytics
- Session replay
- Feature flags

- [x] Ship the onboarding experiment
- [ ] Review session recordings
  - [ ] Share findings with the team

[Open PostHog](https://posthog.com)`,
    },
}

export const QueryBlock: Story = {
    args: {
        value: queryNotebook,
    },
}

export const ComponentCatalog: Story = {
    args: {
        value: componentCatalogNotebook,
    },
}

export const Embeds: Story = {
    args: {
        value: embedsNotebook,
    },
}

export const MermaidDiagram: Story = {
    args: {
        value: mermaidNotebook,
        mode: 'view',
    },
    // Mermaid renders asynchronously (lazy chunk + async render); wait for the finished SVG
    // so the snapshot isn't captured mid-render.
    parameters: {
        testOptions: { waitForSelector: '[data-attr="mermaid-rendered"]' },
    },
}

export const MermaidDiagramWide: Story = {
    args: {
        value: wideMermaidNotebook,
        mode: 'view',
    },
    // Mermaid renders asynchronously (lazy chunk + async render); wait for the finished SVG
    // so the snapshot isn't captured mid-render.
    parameters: {
        testOptions: { waitForSelector: '[data-attr="mermaid-rendered"]' },
    },
}

export const MermaidDiagramFallback: Story = {
    args: {
        value: invalidMermaidNotebook,
        mode: 'view',
    },
    // Invalid mermaid resolves asynchronously to the error fallback; wait for it before snapshotting.
    parameters: {
        testOptions: { waitForSelector: '[data-attr="mermaid-error"]' },
    },
}

export const MalformedMarkdownRecovery: Story = {
    args: {
        value: malformedNotebook,
    },
}

export const InvalidComponentProps: Story = {
    args: {
        value: invalidPropsNotebook,
    },
}

export const ViewMode: Story = {
    args: {
        value: componentCatalogNotebook,
        mode: 'view',
    },
}

export const EditMode: Story = {
    args: {
        value: componentCatalogNotebook,
        mode: 'edit',
    },
}

export const SelectionToolbarState: Story = {
    args: {
        value: `# Selection toolbar

Select part of this paragraph to format it from the inline toolbar.`,
    },
}

export const SlashMenuAndInsertion: Story = {
    args: {
        value: '',
        initialInsertMenu: { nodeIndex: 0, query: '' },
        // Extra commands are injected by the caller (the scenes layer wires up "Saved insight"); a stub
        // command keeps that row present in the menu snapshot without mounting any real modal.
        extraInsertCommands: () => [
            {
                key: 'query-saved-insight',
                label: 'Saved insight',
                category: 'Insight',
                icon: <IconGraph />,
                run: () => {},
            },
        ],
    },
}

export const MockedCollaboration: Story = {
    args: {
        value: textNotebook,
    },
    render: (props) => <CollaborationNotebook {...props} />,
}
