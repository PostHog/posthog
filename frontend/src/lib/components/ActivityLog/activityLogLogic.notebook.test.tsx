import { ActivityLogItem, ActivityScope, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import '@testing-library/jest-dom'
import { InsightShortId } from '~/types'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { render } from '@testing-library/react'

describe('the activity log logic', () => {
    describe('humanizing notebooks', () => {
        it('can handle notebook changes', async () => {
            const notebookChange = {
                user: {
                    first_name: 'paul2',
                    email: 'paul.dambra@gmail.com',
                },
                unread: true,
                is_system: false,
                activity: 'updated',
                item_id: '01891c30-e217-0000-f8af-fd0995850693',
                scope: ActivityScope.NOTEBOOK,
                detail: {
                    merge: null,
                    name: 'my notebook title',
                    type: undefined,
                    changes: [
                        {
                            type: 'Notebook',
                            after: {
                                type: 'doc',
                                content: [
                                    {
                                        type: 'heading',
                                        attrs: {
                                            level: 1,
                                        },
                                        content: [
                                            {
                                                text: 'testing my notebook',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                    {
                                        type: 'paragraph',
                                        content: [
                                            {
                                                text: 'here is where my amazing content i',
                                                type: 'text',
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
                                                text: 'I am stealing your amazing content',
                                                type: 'text',
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
                                                text: 'more of the changin',
                                                type: 'text',
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
                                                text: 'I am user one, my last content load ended "changin" even though it should have ended "changing"',
                                                type: 'text',
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
                                                text: 'this edit ends with the letter r',
                                                type: 'text',
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
                                                text: 'what',
                                                type: 'text',
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
                                                text: 'ah, is it when no new line',
                                                type: 'text',
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
                                                text: 'changing',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                ],
                            },
                            field: 'content',
                            action: 'changed',
                            before: {
                                type: 'doc',
                                content: [
                                    {
                                        type: 'heading',
                                        attrs: {
                                            level: 1,
                                        },
                                        content: [
                                            {
                                                text: 'testing my notebook',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                    {
                                        type: 'paragraph',
                                        content: [
                                            {
                                                text: 'here is where my amazing content i',
                                                type: 'text',
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
                                                text: 'I am stealing your amazing content',
                                                type: 'text',
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
                                                text: 'more of the changin',
                                                type: 'text',
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
                                                text: 'I am user one, my last content load ended "changin" even though it should have ended "changing"',
                                                type: 'text',
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
                                                text: 'this edit ends with the letter r',
                                                type: 'text',
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
                                                text: 'what',
                                                type: 'text',
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
                                                text: 'ah, is it when no new line',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                        {
                            type: 'Notebook',
                            after: 12,
                            field: 'version',
                            action: 'changed',
                            before: 11,
                        },
                    ],
                    trigger: null,
                    short_id: 'TzPqJ307' as InsightShortId,
                },
                created_at: '2023-07-03T14:45:48.341877Z',
            } satisfies ActivityLogItem

            const humanizedActivityLogItems = humanize([notebookChange], describerFor)
            expect(humanizedActivityLogItems).toHaveLength(1)
            const renderedContent = render(<>{humanizedActivityLogItems[0].description}</>).container

            expect(renderedContent).toHaveTextContent('paul2 changed content on my notebook title')
        })
    })
})
