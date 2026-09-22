import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { NavExperimentTab, panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../ProjectTree/projectTreeDataLogic'
import { NavBar } from './NavBar'
import { navAppsTabLogic } from './tabs/navAppsTabLogic'

const files: FileSystemEntry[] = [
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
    {
        id: 'notebook-1',
        path: 'Product research/Onboarding notes',
        type: 'notebook',
        ref: 'notes001',
        href: '/notebooks/notes001',
    },
    { id: 'flag-1', path: 'New checkout', type: 'feature_flag', ref: '1', href: '/feature_flags/1' },
]
const starred: FileSystemEntry[] = [
    { id: 'star-1', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
    { id: 'star-2', path: 'Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
    { id: 'star-3', path: 'Product research', type: 'folder', ref: 'Product research' },
]

function SidebarStory({
    tab = 'home',
    search = '',
    collapsed = false,
    empty = false,
}: {
    tab?: NavExperimentTab
    search?: string
    collapsed?: boolean
    empty?: boolean
}): JSX.Element {
    const { setNavExperimentTab, toggleLayoutNavCollapsed, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { setSearch } = useActions(navAppsTabLogic)
    const { loadShortcutsSuccess } = useActions(projectTreeDataLogic)
    useOnMountEffect(() => {
        setNavExperimentTab(tab)
        toggleLayoutNavCollapsed(collapsed)
        clearActivePanelIdentifier()
        setSearch(search)
        loadShortcutsSuccess(empty ? [] : starred)
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
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system': ({ request: req }) => {
                    const params = new URL(req.url).searchParams
                    const parent = params.get('parent')
                    const search = params.get('search')?.toLowerCase() ?? ''
                    const results = files.filter((file) =>
                        parent !== null
                            ? file.path.split('/').slice(0, -1).join('/') === parent
                            : file.type !== 'folder' && file.path.toLowerCase().includes(search)
                    )
                    return [200, { results, count: results.length, next: null, has_more: false }]
                },
                '/api/environments/:team_id/file_system_shortcut/': [200, { results: starred }],
            },
            post: {
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
export const Files: Story = { args: { tab: 'files' } }
export const Search: Story = { args: { search: 'data' } }
export const NoResults: Story = { args: { search: 'nothing-matches' } }
export const Collapsed: Story = { args: { collapsed: true } }
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
