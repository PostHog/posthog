import '@testing-library/jest-dom'
import { render } from '@testing-library/react'

import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope, InsightShortId } from '~/types'

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
                            type: ActivityScope.NOTEBOOK,
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
                                                text: 'here is where my amazing content is',
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
                                                text: 'testing my notebook (before)',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                    {
                                        type: 'paragraph',
                                        content: [
                                            {
                                                text: 'here is where my amazing content will be',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                        {
                            type: ActivityScope.NOTEBOOK,
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
