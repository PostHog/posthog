import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { within, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useActions, useMountedLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { organizationLogic } from 'scenes/organizationLogic'

import { mswDecorator } from '~/mocks/browser'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { DecideRequestApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { NavExperimentTab, panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'
import { NavBar } from './NavBar'
import { navAppsTabLogic } from './tabs/navAppsTabLogic'
import { FILES_TREE_KEY, navFilesTabLogic } from './tabs/navFilesTabLogic'
import { navRecentsLogic } from './tabs/navRecentsLogic'

const files: FileSystemEntry[] = [
    { id: 'users-folder', path: 'Users', type: 'folder' },
    { id: 'home-folder', path: 'Users/Alex Example', type: 'folder' },
    { id: 'other-home-folder', path: 'Users/Alex Example (1)', type: 'folder' },
    { id: 'folder-1', path: 'Getting started', type: 'folder' },
    { id: 'dashboard-1', path: 'Getting started/Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
    {
        id: 'insight-1',
        path: 'Getting started/Weekly signups',
        type: 'insight',
        ref: 'signup01',
        href: '/insights/signup01',
    },
    { id: 'folder-2', path: 'Product research', type: 'folder' },
    { id: 'folder-3', path: 'Product research/Ideas', type: 'folder' },
    {
        id: 'notebook-1',
        path: 'Product research/Onboarding notes',
        type: 'notebook',
        ref: 'notes001',
        href: '/notebooks/notes001',
    },
    { id: 'flag-1', path: 'New checkout', type: 'feature_flag', ref: '1', href: '/feature_flags/1' },
]
const ownedFileIds = new Set(['dashboard-1', 'notebook-1'])
const starred: FileSystemEntry[] = [
    { id: 'star-home', path: 'Alex Example', type: 'folder', ref: 'Users/Alex Example' },
    { id: 'star-1', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
    { id: 'star-2', path: 'Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
    { id: 'star-3', path: 'Product research', type: 'folder', ref: 'Product research' },
    { id: 'star-4', path: 'Ideas', type: 'folder', ref: 'Product research/Ideas' },
]

function SidebarStory({
    tab = 'home',
    search = '',
    collapsed = false,
    overlay = false,
    empty = false,
    recentsCollapsed = false,
    folderToOpen,
}: {
    tab?: NavExperimentTab
    search?: string
    collapsed?: boolean
    overlay?: boolean
    empty?: boolean
    recentsCollapsed?: boolean
    folderToOpen?: string
}): JSX.Element {
    const { setNavExperimentTab, toggleLayoutNavCollapsed, clearActivePanelIdentifier, setNavOverlayOpen } =
        useActions(panelLayoutLogic)
    const { setRecentsCollapsed } = useActions(navRecentsLogic)
    const { setSearch } = useActions(navAppsTabLogic)
    const { loadShortcutsSuccess } = useActions(projectTreeDataLogic)
    useMountedLogic(navFilesTabLogic)
    useOnMountEffect(() => {
        setNavExperimentTab(tab)
        toggleLayoutNavCollapsed(collapsed)
        setNavOverlayOpen(overlay)
        clearActivePanelIdentifier()
        setSearch(search)
        if (tab === 'files') {
            projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' }).actions.setSearchTerm(search)
        }
        setRecentsCollapsed(recentsCollapsed)
        loadShortcutsSuccess(empty ? [] : starred)
        if (folderToOpen !== undefined) {
            navFilesTabLogic.actions.openFolder(folderToOpen)
        }
    })
    return <NavBar />
}

const meta: Meta<typeof SidebarStory> = {
    title: 'Layout/Apps and files',
    component: SidebarStory,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [
            ...new Set(
                [...getDefaultTreeProducts(), ...getDefaultTreeDataAndPeople()].flatMap((item) =>
                    item.flag ? [item.flag] : []
                )
            ),
            FEATURE_FLAGS.PRODUCT_AUTONOMY,
            FEATURE_FLAGS.SIMPLE_SIDEPANEL,
            FEATURE_FLAGS.ML_INFERENCE_DECISIONS,
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system': ({ request: req }) => {
                    const params = new URL(req.url).searchParams
                    const parent = params.get('parent')
                    const search = params.get('search')?.toLowerCase() ?? ''
                    const type = search
                        .split(' ')
                        .find((part) => part.startsWith('type:'))
                        ?.slice(5)
                    const query = search
                        .split(' ')
                        .filter((part) => !part.includes(':'))
                        .join(' ')
                    const onlyMine = search.split(' ').includes('user:me')
                    const results = files.filter((file) =>
                        parent !== null
                            ? file.path.split('/').slice(0, -1).join('/') === parent
                            : file.type !== 'folder' &&
                              (!onlyMine || ownedFileIds.has(file.id)) &&
                              (!type || file.type === type) &&
                              file.path.toLowerCase().includes(query)
                    )
                    return [200, { results, count: results.length, next: null, has_more: false }]
                },
                '/api/environments/:team_id/file_system_shortcut/': [200, { results: starred }],
            },
            post: {
                '/api/projects/:team_id/ml_inference/decisions/decide/': async ({ request }) => {
                    const { questions } = (await request.json()) as DecideRequestApi
                    return [
                        200,
                        {
                            model: 'storybook',
                            input_tokens: 1,
                            latency_ms: 1,
                            answers: Object.fromEntries(
                                Object.entries(questions).map(([key, question]) => [
                                    key,
                                    {
                                        type: 'noul',
                                        probability: question.instructions.includes('App: Web analytics.')
                                            ? 0.98
                                            : question.instructions.includes('App: Product analytics.')
                                              ? 0.8
                                              : 0.1,
                                    },
                                ])
                            ),
                        },
                    ]
                },
                '/api/projects/:team_id/file_system/home_folder/': [
                    200,
                    { id: 'home-folder', path: 'Users/Alex Example' },
                ],
                '/api/environments/:team_id/file_system_shortcut/': async ({ request: req }) => [
                    201,
                    { ...((await req.json()) as object), id: 'star-new' },
                ],
            },
            delete: {
                '/api/environments/:team_id/file_system_shortcut/:id/': [204],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof SidebarStory>
export const Apps: Story = {}
export const ConfigureStarred: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const body = within(canvasElement.ownerDocument.body)
        await userEvent.click(await canvas.findByLabelText('Starred options'))
        await userEvent.click(await body.findByText('Configure starred', { exact: true }))
    },
}
export const ConfigureStarredWithoutAIConsent: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
                ],
            },
        }),
    ],
    play: async (context) => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        await ConfigureStarred.play!(context)
    },
}
export const ConfigureStarredRanked: Story = {
    play: async (context) => {
        await ConfigureStarred.play!(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await userEvent.click(body.getByText('Track website visitors', { exact: true }))
        await waitFor(() => {
            if (navAppsTabLogic.values.rankedConfigurableApps[0]?.path !== 'Web analytics') {
                throw new Error('Waiting for app rankings')
            }
        })
    },
}
export const ConfigureStarredNoMatches: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/ml_inference/decisions/decide/': async ({ request }) => {
                    const { questions } = (await request.json()) as DecideRequestApi
                    return [
                        200,
                        {
                            model: 'storybook',
                            input_tokens: 1,
                            latency_ms: 1,
                            answers: Object.fromEntries(
                                Object.keys(questions).map((key) => [key, { type: 'noul', probability: 0.1 }])
                            ),
                        },
                    ]
                },
            },
        }),
    ],
    play: async (context) => {
        await ConfigureStarred.play!(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await userEvent.type(body.getByLabelText('Filter by jev'), 'Plan a hiking trip')
        await body.findByText(
            'No apps meet the match threshold. Try another description or choose from the apps below.'
        )
    },
}
export const ConfigureStarredUnavailable: Story = {
    decorators: [
        mswDecorator({
            post: { '/api/projects/:team_id/ml_inference/decisions/decide/': [503, { detail: 'Unavailable' }] },
        }),
    ],
    play: async (context) => {
        await ConfigureStarred.play!(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await userEvent.click(body.getByText('Query databases', { exact: true }))
        await body.findByText(
            'Jev could not suggest apps. Edit your description to try again, or choose from all apps below.'
        )
    },
}
export const ConfigureStarredDark: Story = { ...ConfigureStarredRanked, globals: { theme: 'dark' } }
export const ConfigureStarredNarrow: Story = {
    ...ConfigureStarredRanked,
    parameters: { testOptions: { viewport: { width: 600, height: 900 } } },
}
export const Files: Story = { args: { tab: 'files' } }
export const FilesOptions: Story = {
    ...Files,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const body = within(canvasElement.ownerDocument.body)
        const options = await canvas.findByLabelText('Files options')
        await userEvent.click(options)
        await userEvent.click(body.getByText('Filters', { exact: true }))
        await userEvent.click(body.getByText('Only my stuff', { exact: true }))
        await userEvent.click(body.getByText('Notebook', { exact: true }))
        await userEvent.click(body.getByText('Only my stuff', { exact: true }))
        await userEvent.click(body.getByText('Notebook', { exact: true }))
        await userEvent.click(canvasElement.ownerDocument.body)
        await userEvent.click(options)
    },
}
export const OpenFolder: Story = { args: { collapsed: true, folderToOpen: 'Product research' } }
export const Chat: Story = {
    args: { tab: 'chat' },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/conversations/': [
                    200,
                    {
                        results: ['Review signup trends', 'Explore checkout events'].map((title, index) => ({
                            id: `chat-${index}`,
                            title,
                            status: 'idle',
                            type: 'assistant',
                            created_at: new Date().toISOString(),
                            updated_at: new Date().toISOString(),
                            user: MOCK_DEFAULT_BASIC_USER,
                        })),
                        next: null,
                    },
                ],
            },
        }),
    ],
}
export const FilesSearch: Story = { args: { tab: 'files', search: 'Weekly' } }
export const FilesFiltered: Story = { args: { tab: 'files', search: 'type:notebook' } }
export const FilesOnlyMine: Story = { args: { tab: 'files', search: 'user:me' } }
export const FilesNoResults: Story = { args: { tab: 'files', search: 'nothing-matches' } }
export const Search: Story = { args: { search: 'data' } }
export const NoResults: Story = { args: { search: 'nothing-matches' } }
export const Collapsed: Story = { args: { collapsed: true } }
export const FilesCollapsed: Story = { args: { collapsed: true, tab: 'files' } }
export const AppsOverlay: Story = { args: { collapsed: true, overlay: true } }
export const FilesOverlay: Story = { args: { collapsed: true, overlay: true, tab: 'files' } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="[--project-navbar-width:180px]">
                <Story />
            </div>
        ),
    ],
}
export const FilesNarrow: Story = { args: { tab: 'files' }, decorators: Narrow.decorators }
export const Dark: Story = { globals: { theme: 'dark' } }
export const FilesDark: Story = { args: { tab: 'files' }, globals: { theme: 'dark' } }
export const EmptyStarred: Story = {
    args: { empty: true },
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/file_system_shortcut/': [200, { results: [] }] } })],
}

export const FilesEmptyStarred: Story = {
    ...EmptyStarred,
    args: { tab: 'files', empty: true },
}

export const FilesRecentsCollapsed: Story = { args: { tab: 'files', recentsCollapsed: true } }
export const FilesLongTree: Story = {
    args: { tab: 'files' },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system': [
                    200,
                    {
                        results: Array.from({ length: 40 }, (_, index) => ({
                            id: `long-file-${index}`,
                            path: `Report ${String(index + 1).padStart(2, '0')}`,
                            type: 'dashboard',
                            ref: String(index + 1000),
                            href: `/dashboard/${index + 1000}`,
                        })),
                        count: 40,
                        next: null,
                        has_more: false,
                    },
                ],
            },
        }),
    ],
}

export const FlagOff: Story = { parameters: { featureFlags: [] } }
export const FlagOffAfterFiles: Story = {
    args: { tab: 'files', recentsCollapsed: true },
    parameters: { featureFlags: [] },
}
export const FlagOffCollapsed: Story = { args: { collapsed: true }, parameters: { featureFlags: [] } }
export const FlagOffFlatNav: Story = {
    args: { tab: 'files', recentsCollapsed: true },
    parameters: { featureFlags: [FEATURE_FLAGS.FLAT_NAV] },
}
