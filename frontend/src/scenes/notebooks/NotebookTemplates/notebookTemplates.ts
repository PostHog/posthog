import { NotebookType, UserBasicType } from '~/types'

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
        short_id: 'template-introduction',
        title: 'Introducing Notebooks! 🥳',
        created_at: '2023-06-02T00:00:00Z',
        last_modified_at: '2023-06-02T00:00:00Z',
        created_by: TEMPLATE_USERS.posthog,
        last_modified_by: TEMPLATE_USERS.posthog,
        version: 1,
        content: {
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Introducing Notebooks! 🥳' }],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Notebooks are a powerful way of working with all of the various parts of PostHog, allowing you to bring Insights, Replays, Feature Flags, Events and much more into one place. Whether it is an ',
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'ad-hoc analysis' },
                        { type: 'text', text: ' or a ' },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'bug investigation' },
                        { type: 'text', text: ' or a ' },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'feature release' },
                        {
                            type: 'text',
                            text: '. We have only just got started with Notebooks so try it out and let us know what you think.',
                        },
                    ],
                },
                { type: 'paragraph' },
                { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'General text editing' }] },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Notebooks support all sorts of typical text editing features such as Headings, Bold, Italic, Lists etc. Currently the only supported method of doing these is via ',
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'Markdown.' },
                    ],
                },
                { type: 'paragraph' },
                { type: 'paragraph', content: [{ type: 'text', text: '# Heading 1' }] },
                { type: 'paragraph', content: [{ type: 'text', text: '## Heading 2' }] },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: '### Heading 3 ' },
                        { type: 'text', marks: [{ type: 'italic' }], text: '(you get the idea...)' },
                    ],
                },
                { type: 'paragraph', content: [{ type: 'text', text: '- List ' }] },
                { type: 'paragraph', content: [{ type: 'text', text: '1. Numbered list' }] },
                { type: 'paragraph', content: [{ type: 'text', text: '**Bold**' }] },
                { type: 'paragraph', content: [{ type: 'text', text: '_italic_' }] },
                { type: 'paragraph', content: [{ type: 'text', text: '`code`' }] },
                { type: 'paragraph' },
                {
                    type: 'heading',
                    attrs: { level: 2 },
                    content: [{ type: 'text', text: 'What PostHog things are currently supported?' }],
                },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'The real power of Notebooks comes from pulling various PostHog resources into the document. Whilst this feature is in ',
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'beta' },
                        {
                            type: 'text',
                            text: ", you will find that some things work and others don't... yet. We will keep this document updated with information about what is working and what isn't so be sure to check back.",
                        },
                    ],
                },
                { type: 'paragraph' },
                {
                    type: 'heading',
                    attrs: { level: 3 },
                    content: [{ type: 'text', text: 'Adding within the Notebook' }],
                },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'When you have your cursor on an empty line a ' },
                        { type: 'text', marks: [{ type: 'code' }], text: '+' },
                        {
                            type: 'text',
                            text: ' button will appear. Clicking that gives you a drop down of various things you can add, from a ',
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'Trend graph ' },
                        { type: 'text', text: 'to an ' },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'Session Replay list.' },
                    ],
                },
                { type: 'paragraph' },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'You can also trigger this with a "slash command" by typing ' },
                        { type: 'text', marks: [{ type: 'code' }], text: '/' },
                        { type: 'text', text: ' . Try ' },
                        { type: 'text', marks: [{ type: 'code' }], text: '/insight' },
                        { type: 'text', text: ' to filter for things you would typically find in Insights.' },
                    ],
                },
                { type: 'paragraph' },
                { type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: 'Drag and Drop' }] },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'The primary way of getting things into a Notebook ' },
                        { type: 'text', marks: [{ type: 'italic' }], text: 'currently' },
                        { type: 'text', text: ' is ' },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'Drag and Drop' },
                        {
                            type: 'text',
                            text: '. You can drag many things from elsewhere in PostHog into a Notebook that is pinned to the side.',
                        },
                    ],
                },
                { type: 'paragraph' },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: "We're quickly adding support for more and more things around PostHog but to see what is currently supported you just have to ",
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'hold down the alt / option key' },
                        {
                            type: 'text',
                            text: ' and any supported elements will be highlighted. You can then click and drag it into the Notebook Sidebar to add it to the currently opened Notebook.',
                        },
                    ],
                },
                { type: 'paragraph' },
                {
                    type: 'paragraph',
                    content: [{ type: 'text', marks: [{ type: 'bold' }], text: 'Currently we support' }],
                },
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '✅ Replay' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [{ type: 'text', text: '✅ Replay Playlists (saved filters)' }],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '✅ Persons' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [
                                        {
                                            type: 'text',
                                            text: '✅ Data Exploration nodes (such as the Event Explorer) (partially)',
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
                                    content: [{ type: 'text', text: '✅ Feature Flags (partially)' }],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [{ type: 'text', text: '✅ Insights (partially working)' }],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '✅ HogQL' }] }],
                        },
                    ],
                },
                { type: 'paragraph' },
                { type: 'paragraph', content: [{ type: 'text', marks: [{ type: 'bold' }], text: "What's next?" }] },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'We have big plans for Notebooks and given that we develop in the open you can follow our roadmap on Github ',
                        },
                        {
                            type: 'text',
                            marks: [
                                { type: 'link', attrs: { href: 'https://github.com/PostHog/posthog/issues/15680' } },
                            ],
                            text: 'https://github.com/PostHog/posthog/issues/15680',
                        },
                        { type: 'text', text: ' ' },
                    ],
                },
                { type: 'paragraph' },
                { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Give me an example...' }] },
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Sure! Below is a Trends chart. This was added by typing ' },
                        { type: 'text', marks: [{ type: 'code' }], text: '/trends' },
                        { type: 'text', text: ' and pressing enter.' },
                    ],
                },
                {
                    type: 'paragraph',
                    content: [{ type: 'text', text: 'If you make a copy of this Notebook you can edit it inline.' }],
                },
                { type: 'paragraph' },
                {
                    type: 'ph-query',
                    attrs: {
                        height: null,
                        title: 'Trends',
                        nodeId: '098559a2-33d6-4da1-a836-f9f332dd7082',
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [{ kind: 'EventsNode', math: 'total', name: '$pageview', event: '$pageview' }],
                                interval: 'day',
                                trendsFilter: { display: 'ActionsLineGraph' },
                                filterTestAccounts: false,
                            },
                        },
                    },
                },
            ],
        },
    },
].map((template) => ({
    ...template,
    is_template: true,
}))
