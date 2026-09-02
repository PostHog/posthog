import { Meta, StoryObj } from '@storybook/react'

import { SkillPicker } from './SkillPicker'

const meta: Meta<typeof SkillPicker> = {
    title: 'Components/SkillPicker',
    component: SkillPicker,
}
export default meta

type Story = StoryObj<typeof SkillPicker>

const GROUPS = [
    {
        key: 'teammates',
        label: 'Perspectives from your teammates',
        skills: [
            {
                name: 'review-hog-perspective-accessibility',
                description:
                    'Reviews changed UI code for keyboard navigation, focus handling, and screen reader support.',
            },
        ],
    },
    {
        key: 'store',
        label: 'All team skills',
        skills: [
            {
                name: 'api-design-guidelines',
                description: 'How this team designs REST endpoints: naming, pagination, error shapes.',
            },
            {
                name: 'writing-database-migrations',
                description: 'Safe migration practices for large tables.',
            },
            { name: 'undocumented-helper', description: '' },
        ],
    },
]

export const Default: Story = {
    args: {
        groups: GROUPS,
        selectLabel: 'Use this skill',
        onSelect: () => {},
        loadBody: () => Promise.resolve('# Example skill\n\nSome markdown body content.'),
    },
}

export const Loading: Story = {
    args: {
        groups: [],
        loading: true,
        onSelect: () => {},
    },
    parameters: {
        testOptions: {
            // This story renders skeletons forever by design; the default wait would time out.
            waitForLoadersToDisappear: false,
        },
    },
}

export const Empty: Story = {
    args: {
        groups: [{ key: 'store', label: 'All team skills', skills: [] }],
        emptyMessage: 'Your team has no other skills yet.',
        onSelect: () => {},
    },
}
