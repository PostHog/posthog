import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { TagsTable } from './TagsTable'

const tags = [
    { id: '01900000-0000-7000-8000-000000000001', name: 'on-boarding', usage_count: 3 },
    { id: '01900000-0000-7000-8000-000000000002', name: 'onboarding', usage_count: 1 },
    { id: '01900000-0000-7000-8000-000000000003', name: 'unused', usage_count: 0 },
]
const organization = { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Admin }

const meta: Meta<typeof TagsTable> = {
    title: 'Scenes-Other/Data management/Tags',
    component: TagsTable,
    parameters: {
        layout: 'padded',
        mockDate: '2026-11-24',
        featureFlags: [FEATURE_FLAGS.TAG_MANAGEMENT],
        testOptions: { waitForSelector: '[data-attr="tag-management-actions"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': { ...MOCK_DEFAULT_USER, organization },
                '/api/organizations/@current/': organization,
                '/api/projects/:project_id/tag_definitions/': {
                    results: tags,
                    count: tags.length,
                    next: null,
                    previous: null,
                },
                '/api/projects/:project_id/tag_definitions/:id/merge_preview/': {
                    tag: tags[1],
                    source_count: 3,
                    target_count: 1,
                    overlap_count: 1,
                    result_count: 3,
                },
            },
            patch: { '/api/projects/:project_id/tag_definitions/:id/': tags[0] },
            post: {
                '/api/projects/:project_id/tag_definitions/:id/merge/': {
                    tag: { ...tags[1], usage_count: 3 },
                    moved_count: 2,
                    overlap_count: 1,
                    usage_count: 3,
                },
            },
            delete: { '/api/projects/:project_id/tag_definitions/:id/': [204] },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof TagsTable>

const quillParameters = { featureFlags: [FEATURE_FLAGS.TAG_MANAGEMENT, FEATURE_FLAGS.TODAY_RAIL_NAV] }
const modalParameters = {
    testOptions: {
        waitForSelector: '[role="dialog"], [role="alertdialog"]',
        snapshotTargetSelector: '[role="dialog"], [role="alertdialog"]',
    },
}

async function openTagAction(canvasElement: HTMLElement, tagName: string, action: string): Promise<void> {
    await userEvent.click(await within(canvasElement).findByRole('button', { name: `Actions for ${tagName}` }))
    await userEvent.click(await within(document.body).findByText(action, { exact: true }))
}

async function openMergePreview(canvasElement: HTMLElement, destinationRole: 'button' | 'option'): Promise<void> {
    await openTagAction(canvasElement, tags[0].name, 'Merge into another tag')
    const page = within(document.body)
    await userEvent.click(await page.findByPlaceholderText('Search existing tags'))
    await userEvent.click(await page.findByRole(destinationRole, { name: tags[1].name }))
    await page.findByText(/assignments after merge/i)
}

export const Catalog: Story = {}
export const QuillCatalog: Story = {
    parameters: quillParameters,
}
export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/tag_definitions/': { results: [], count: 0, next: null, previous: null },
            },
        }),
    ],
    parameters: { testOptions: { waitForSelector: 'text=No tags yet.' } },
}

export const Rename: Story = {
    parameters: modalParameters,
    play: async ({ canvasElement }) => {
        await openTagAction(canvasElement, tags[0].name, 'Rename')
        await within(document.body).findByLabelText('Tag name')
    },
}

export const QuillRename: Story = {
    ...Rename,
    parameters: { ...modalParameters, ...quillParameters },
}

export const MergePreview: Story = {
    parameters: modalParameters,
    play: async ({ canvasElement }) => {
        await openMergePreview(canvasElement, 'button')
    },
}

export const QuillMergePreview: Story = {
    parameters: { ...modalParameters, ...quillParameters },
    play: async ({ canvasElement }) => {
        await openMergePreview(canvasElement, 'option')
    },
}

export const DeleteUnused: Story = {
    parameters: modalParameters,
    play: async ({ canvasElement }) => {
        await openTagAction(canvasElement, tags[2].name, 'Delete unused tag')
        await within(document.body).findByText('This tag has no assignments. Deleting it cannot be undone.')
    },
}

export const QuillDeleteUnused: Story = {
    ...DeleteUnused,
    parameters: { ...modalParameters, ...quillParameters },
}
