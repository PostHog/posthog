import { AccessControlLevel, UserBasicType } from '~/types'

import { NotebookType } from '../types'

const TEMPLATE_USERS: Record<string, UserBasicType> = {
    posthog: {
        id: 1,
        uuid: 'posthog@posthog.com',
        distinct_id: '1',
        first_name: 'PostHog',
        email: 'posthog@posthog.com',
    },
}

export const LOCAL_NOTEBOOK_TEMPLATES: NotebookType[] = [
    {
        id: 'template-introduction',
        short_id: 'template-introduction',
        title: 'Introducing Notebooks! 🥳',
        created_at: '2023-06-02T00:00:00Z',
        last_modified_at: '2023-06-02T00:00:00Z',
        created_by: TEMPLATE_USERS.posthog,
        last_modified_by: TEMPLATE_USERS.posthog,
        user_access_level: AccessControlLevel.Viewer,
        version: 1,
        content: {
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: {
                        level: 1,
                    },
                    content: [
                        {
                            type: 'text',
                            text: 'Introducing Notebooks! 🥳',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Notebooks are a powerful way to collate, analyze, and share PostHog data with others:',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            marks: [
                                                {
                                                    type: 'bold',
                                                },
                                            ],
                                            text: 'Investigating a bug report?',
                                        },
                                        {
                                            type: 'text',
                                            text: ' Drag and drop session replays into a scratchpad and watch them as normal, or add timestamped comments to break things down.',
                                        },
                                        {
                                            type: 'hardBreak',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            marks: [
                                                {
                                                    type: 'bold',
                                                },
                                            ],
                                            text: 'Researching a new idea?',
                                        },
                                        {
                                            type: 'text',
                                            text: ' Collect insights and add them to your proposal seamlessly, alongside survey results or cohorts.',
                                        },
                                        {
                                            type: 'hardBreak',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            marks: [
                                                {
                                                    type: 'bold',
                                                },
                                            ],
                                            text: 'Planning a launch? ',
                                        },
                                        {
                                            type: 'text',
                                            text: 'Embed the feature flags, events, persons, or cohorts you’ll need to deploy changes and track success.',
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'There’s no limit to how many notebooks you can create, or how you can share them within your organization, though we block multiplayer editing to stop things getting messy.',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'heading',
                    attrs: {
                        level: 2,
                    },
                    content: [
                        {
                            type: 'text',
                            text: 'Editing in notebooks',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Notebooks support all sorts of typical text editing features such as headings, bold, italic, numbered and un-numbered lists etc:',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '# Heading 1',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '## Heading 2',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '### Heading 3 ',
                                        },
                                        {
                                            type: 'text',
                                            marks: [
                                                {
                                                    type: 'italic',
                                                },
                                            ],
                                            text: '(you get the idea...)',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '- List ',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '1. Numbered list',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '**Bold**',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '_italic_',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '`code`',
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'You can also add images:',
                        },
                    ],
                },
                {
                    type: 'ph-image',
                    attrs: {
                        height: 451,
                        title: null,
                        nodeId: '71f6afaa-90be-44fd-b4d7-48f8d8baf4bd',
                        __init: null,
                        children: null,
                        file: null,
                        src: 'https://us.posthog.com/uploaded_media/018c494d-132b-0000-2004-8861f35c13b5',
                    },
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'hardBreak',
                        },
                        {
                            type: 'text',
                            text: 'And embed iframe elements, such as YouTube videos:',
                        },
                    ],
                },
                {
                    type: 'ph-embed',
                    attrs: {
                        height: 508,
                        title: 'PostHog youtube video',
                        nodeId: '421818d3-65c7-4a14-a22e-924e8c4ee04f',
                        __init: null,
                        children: null,
                        src: 'https://www.youtube.com/embed/2N2cvCmv4us?si=5cFwH3fHX8D-Yh1v',
                        width: null,
                    },
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'hardBreak',
                        },
                    ],
                },
                {
                    type: 'heading',
                    attrs: {
                        level: 2,
                    },
                    content: [
                        {
                            type: 'text',
                            text: 'Adding PostHog data to notebooks',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'The real power of Notebooks comes from pulling various PostHog resources into the document.',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'heading',
                    attrs: {
                        level: 3,
                    },
                    content: [
                        {
                            type: 'text',
                            text: 'Slash commands',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'When you have your cursor on an empty line a ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'code',
                                },
                            ],
                            text: '+',
                        },
                        {
                            type: 'text',
                            text: ' button will appear. Clicking that gives you a drop down of various things you can add, from a ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'bold',
                                },
                            ],
                            text: 'Trend graph ',
                        },
                        {
                            type: 'text',
                            text: 'to a ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'bold',
                                },
                            ],
                            text: 'session replay list.',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'You can also trigger this with a "slash command" by typing ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'code',
                                },
                            ],
                            text: '/',
                        },
                        {
                            type: 'text',
                            text: ' . Try ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'code',
                                },
                            ],
                            text: '/insight',
                        },
                        {
                            type: 'text',
                            text: ' to filter for things you would typically find in Insights.',
                        },
                        {
                            type: 'hardBreak',
                        },
                        {
                            type: 'hardBreak',
                        },
                        {
                            type: 'text',
                            text: "Here's an example of an insight created in a notebook:",
                        },
                    ],
                },
                {
                    type: 'ph-query',
                    attrs: {
                        height: null,
                        title: null,
                        nodeId: '1957c0c0-432f-4b03-9da3-c4ae09a36b98',
                        __init: null,
                        children: null,
                        query: '{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","filterTestAccounts":false,"series":[{"kind":"EventsNode","event":"$pageview","name":"$pageview","math":"dau"}],"interval":"day","trendsFilter":{"display":"ActionsLineGraph"}}}',
                    },
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'heading',
                    attrs: {
                        level: 3,
                    },
                    content: [
                        {
                            type: 'text',
                            text: 'Drag and Drop',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'You can also drag and drop PostHog elements into a notebook pinned to the sidebar, such as:',
                        },
                        {
                            type: 'hardBreak',
                        },
                    ],
                },
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Individual replays',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Replay Playlists (saved filters)',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'SQL tables',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Feature flags',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Experiments',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Surveys',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'Insights',
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: 'And a whole bunch more...',
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'ph-image',
                    attrs: {
                        height: 450,
                        title: '',
                        nodeId: '89276c11-147a-4a1a-b091-514d3b9c9e9f',
                        __init: null,
                        children: null,
                        file: null,
                        src: 'https://us.posthog.com/uploaded_media/018c496c-d79a-0000-bbc8-fdb0c77ec46f',
                    },
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'heading',
                    attrs: {
                        level: 2,
                    },
                    content: [
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'bold',
                                },
                            ],
                            text: "What's next?",
                        },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'We have big plans for Notebooks and given that we develop in the open you can follow our',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'bold',
                                },
                            ],
                            text: ' ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'link',
                                    attrs: {
                                        href: 'https://github.com/PostHog/posthog/issues/15680 ',
                                    },
                                },
                                {
                                    type: 'bold',
                                },
                            ],
                            text: 'notebooks roadmap on Github',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'bold',
                                },
                            ],
                            text: '.',
                        },
                    ],
                },
                {
                    type: 'paragraph',
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Notebooks is part of a wider re-imagining of our user experience. You can read more about it this blog post by our Lead Designer: ',
                        },
                        {
                            type: 'text',
                            marks: [
                                {
                                    type: 'link',
                                    attrs: {
                                        href: 'https://posthog.com/blog/posthog-as-a-dev-tool',
                                    },
                                },
                                {
                                    type: 'bold',
                                },
                            ],
                            text: 'What if PostHog looked like a dev tool?',
                        },
                    ],
                },
            ],
        },
    },
].map((template) => ({
    ...template,
    is_template: true,
}))
