import { AccessControlLevel, UserBasicType } from '~/types'

import { buildMarkdownNotebookContent } from '../Notebook/markdownNotebookV2'
import { NotebookType } from '../types'

export interface NotebookTemplate {
    /** Stable id the template preview route resolves. Renaming one is a content migration. */
    short_id: string
    title: string
    /** One line, shown on the template card. */
    description: string
    markdown: string
}

const TEMPLATE_USERS: Record<string, UserBasicType> = {
    posthog: {
        id: 1,
        uuid: 'posthog@posthog.com',
        distinct_id: '1',
        first_name: 'PostHog',
        email: 'posthog@posthog.com',
    },
}

const TEMPLATE_TIMESTAMP = '2023-06-02T00:00:00Z'

const INTRODUCTION_MARKDOWN = `# Introducing Notebooks! 🥳

Notebooks are a powerful way to collate, analyze, and share PostHog data with others:

- **Investigating a bug report?** Drag and drop session replays into a scratchpad and watch them as normal, or add timestamped comments to break things down.
- **Researching a new idea?** Collect insights and add them to your proposal seamlessly, alongside survey results or cohorts.
- **Planning a launch?** Embed the feature flags, events, persons, or cohorts you'll need to deploy changes and track success.

There's no limit to how many notebooks you can create, or how you can share them within your organization, though we block multiplayer editing to stop things getting messy.

## Editing in notebooks

Notebooks support all sorts of typical text editing features such as headings, bold, italic, numbered and un-numbered lists etc:

- \`# Heading 1\`
- \`## Heading 2\`
- \`### Heading 3\` *(you get the idea...)*
- \`- List\`
- \`1. Numbered list\`
- \`**Bold**\`
- \`_italic_\`
- \`\\\`code\\\`\`

You can also add images:

![](https://us.posthog.com/uploaded_media/018c494d-132b-0000-2004-8861f35c13b5)

And embed iframe elements, such as YouTube videos:

<Embed title="PostHog youtube video" src="https://www.youtube.com/embed/2N2cvCmv4us?si=5cFwH3fHX8D-Yh1v" />

## Adding PostHog data to notebooks

The real power of Notebooks comes from pulling various PostHog resources into the document.

### Slash commands

When you have your cursor on an empty line a \`+\` button will appear. Clicking that gives you a drop down of various things you can add, from a **Trend graph** to a **session replay list**.

You can also trigger this with a "slash command" by typing \`/\`. Try \`/insight\` to filter for things you would typically find in Insights.

Here's an example of an insight created in a notebook:

<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","filterTestAccounts":false,"series":[{"kind":"EventsNode","event":"$pageview","name":"$pageview","math":"dau"}],"interval":"day","trendsFilter":{"display":"ActionsLineGraph"}}}} />

### Drag and drop

You can also drag and drop PostHog elements into a notebook pinned to the sidebar, such as:

- Individual replays
- Replay playlists (saved filters)
- SQL tables
- Feature flags
- Experiments
- Surveys
- Insights
- And a whole bunch more...

![](https://us.posthog.com/uploaded_media/018c496c-d79a-0000-bbc8-fdb0c77ec46f)

## What's next?

We have big plans for Notebooks and given that we develop in the open you can follow our [notebooks roadmap on GitHub](https://github.com/PostHog/posthog/issues/15680).

Notebooks is part of a wider re-imagining of our user experience. You can read more about it in this blog post by our Lead Designer: [What if PostHog looked like a dev tool?](https://posthog.com/blog/posthog-as-a-dev-tool)`

const BUG_INVESTIGATION_MARKDOWN = `# Bug investigation

## What's happening

*What breaks, who reported it, and when it started.*

## Impact over time

<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[{"kind":"EventsNode","event":"$exception","math":"total"}],"interval":"day","dateRange":{"date_from":"-14d"}}}} />

## Recent occurrences

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery","select":["*","event","timestamp","person"],"event":"$exception","after":"-7d"}}} />

## Watch it happen

<RecordingPlaylist />

## Steps to reproduce

1. *Where to start.*
2. *What to do.*
3. *What goes wrong.*

## Root cause

*What was actually wrong.*

## Fix and follow-up

- [ ] Fix shipped
- [ ] Regression test added
- [ ] Affected users followed up with`

export const NOTEBOOK_TEMPLATES: NotebookTemplate[] = [
    {
        short_id: 'template-introduction',
        title: 'Introducing Notebooks! 🥳',
        description: 'A tour of what notebooks can do, from text editing to embedded PostHog data.',
        markdown: INTRODUCTION_MARKDOWN,
    },
    {
        short_id: 'template-bug-investigation',
        title: 'Bug investigation',
        description: 'Track down a bug with exception trends, recent occurrences, and session replays.',
        markdown: BUG_INVESTIGATION_MARKDOWN,
    },
]

export const LOCAL_NOTEBOOK_TEMPLATES: NotebookType[] = NOTEBOOK_TEMPLATES.map((template) => ({
    id: template.short_id,
    short_id: template.short_id,
    title: template.title,
    created_at: TEMPLATE_TIMESTAMP,
    last_modified_at: TEMPLATE_TIMESTAMP,
    created_by: TEMPLATE_USERS.posthog,
    last_modified_by: TEMPLATE_USERS.posthog,
    user_access_level: AccessControlLevel.Viewer,
    version: 1,
    is_template: true,
    content: buildMarkdownNotebookContent(template.markdown),
}))
