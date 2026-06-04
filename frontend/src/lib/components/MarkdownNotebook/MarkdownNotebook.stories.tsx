import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { MarkdownNotebook, MarkdownNotebookProps } from './MarkdownNotebook'
import { NotebookCollaborationConflict } from './types'

const textNotebook = `# Weekly activation review

Activation improved after the onboarding changes. **Signup completion** is up, *workspace setup* is steady, and <u>invite acceptance</u> needs a follow-up.

- Review activation trend
- Check enterprise onboarding recordings
- Add notes for the growth sync

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

<Image src="https://res.cloudinary.com/dmukukwp6/image/upload/posthog.com/contents/images/blog/posthog-engineering.png" alt="PostHog engineering" />

<Embed src="https://posthog.com" title="PostHog" />

<Latex content="E=mc^2" />`

const malformedNotebook = `# Broken input

<Query query={{"kind":`

const invalidPropsNotebook = `# Invalid props

<Query />`

type StoryArgs = MarkdownNotebookProps

const meta: Meta<StoryArgs> = {
    title: 'Components/Markdown notebook',
    component: MarkdownNotebook,
    tags: ['autodocs'],
    render: (props) => <ControlledNotebook {...props} />,
}

export default meta

type Story = StoryObj<StoryArgs>

function ControlledNotebook(props: MarkdownNotebookProps): JSX.Element {
    const [value, setValue] = useState(props.value)
    return <MarkdownNotebook {...props} value={value} onChange={setValue} />
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

Normal text with **bold**, *italic*, <u>underline</u>, \`code\`, and [a link](https://posthog.com).`,
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
    },
}

export const MockedCollaboration: Story = {
    args: {
        value: textNotebook,
    },
    render: (props) => <CollaborationNotebook {...props} />,
}
