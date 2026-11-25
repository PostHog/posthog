import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

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
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="tag-management-actions"]' },
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

export const Catalog: Story = {}
export const QuillCatalog: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.TAG_MANAGEMENT, FEATURE_FLAGS.TODAY_RAIL_NAV] },
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
