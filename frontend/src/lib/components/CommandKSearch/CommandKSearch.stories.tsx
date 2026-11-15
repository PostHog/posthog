import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import { CommandKSearch } from './CommandKSearch'
import { commandKSearchLogic } from './commandKSearchLogic'

const minutesAgo = (minutes: number): string => new Date(Date.now() - 1000 * 60 * minutes).toISOString()

const MOCK_ENTRIES = [
    { id: '1', path: 'Key metrics', type: 'dashboard', ref: '1', href: '/dashboard/1', last_viewed_at: minutesAgo(5) },
    { id: '2', path: 'Signup funnel', type: 'insight', ref: '2', href: '/insights/2', last_viewed_at: minutesAgo(30) },
    {
        id: '3',
        path: 'new-onboarding',
        type: 'feature_flag',
        ref: '3',
        href: '/feature_flags/3',
        last_viewed_at: minutesAgo(120),
    },
]

const fileSystemMock = (): [number, unknown] => [200, toPaginatedResponse(MOCK_ENTRIES)]

const MOCKS = {
    '/api/projects/:team_id/file_system/': fileSystemMock,
    '/api/environments/:team_id/file_system/': fileSystemMock,
    '/api/environments/:team_id/file_system/log_view/': () => [200, []],
    '/api/environments/:team_id/persons/': () => [200, EMPTY_PAGINATED_RESPONSE],
    '/api/environments/:team_id/groups/': () => [200, EMPTY_PAGINATED_RESPONSE],
}

const meta: Meta = {
    title: 'Components/Command K search',
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<{}>

function Frame({ text }: { text?: string }): JSX.Element {
    useStorybookMocks({ get: MOCKS })
    useMountedLogic(commandKSearchLogic)
    const { inputChanged } = useActions(commandKSearchLogic)
    useEffect(() => {
        if (text) {
            inputChanged(text, text.length, true)
        }
    }, [text, inputChanged])
    return (
        <div className="flex h-[480px] w-[640px] flex-col overflow-hidden rounded-lg border border-border bg-background">
            <CommandKSearch />
        </div>
    )
}

export const Empty: Story = {
    render: () => <Frame />,
}

export const ChipAndValueSuggestions: Story = {
    render: () => <Frame text="is:dashboard is:" />,
}
