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
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '✅ Recordings' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '✅ Recording Lists' }] }],
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
                                            text: '🤔 Data Exploration nodes (such as the Event Explorer) (partially)',
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
                                    content: [{ type: 'text', text: '🤔 Feature Flags (partially)' }],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [{ type: 'text', text: '🤔 Insights (partially working)' }],
                                },
                            ],
                        },
                    ],
                },
                { type: 'paragraph' },
                {
                    type: 'paragraph',
                    content: [{ type: 'text', marks: [{ type: 'bold' }], text: 'Still on the roadmap is' }],
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
                                            text: '🚧 Ad hoc queries without the need to create an Insight',
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
                                        { type: 'text', text: '🚧 Full interactivity and controls for Insights' },
                                    ],
                                },
                            ],
                        },
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: '🚧 HogQL support' }] }],
                        },
                        {
                            type: 'listItem',
                            content: [
                                {
                                    type: 'paragraph',
                                    content: [{ type: 'text', text: '🚧 Support for unfurling external links ' }],
                                },
                            ],
                        },
                    ],
                },
                { type: 'paragraph' },
                { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Give me an example...' }] },
                {
                    type: 'paragraph',
                    content: [
                        {
                            type: 'text',
                            text: 'Sure!  Below you should see the list of recent recordings. This was added by dragging the header of the Recordings list from the ',
                        },
                        { type: 'text', marks: [{ type: 'bold' }], text: 'Session Replay ' },
                        {
                            type: 'text',
                            text: 'page. Just like anything else in the document you can copy and paste it, rearrange it or even copy it and paste it in a different Notebook.',
                        },
                    ],
                },
                {
                    type: 'ph-recording-playlist',
                    attrs: {
                        filters:
                            '{"session_recording_duration":{"type":"recording","key":"duration","value":3600,"operator":"gt"},"properties":[],"events":[],"actions":[],"date_from":"-7d","date_to":null}',
                    },
                },
            ],
        },
    },
].map((template) => ({
    ...template,
    is_template: true,
}))
