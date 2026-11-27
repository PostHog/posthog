import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { KnowledgeLibraryApi } from '../../generated/api.schemas'
import { LearnedLibrariesSetting } from './LearnedLibrariesSetting'

const libraries: KnowledgeLibraryApi[] = [
    { id: 'library-learned', name: 'Learned', is_default: true, source_count: 9, repos: [] },
    { id: 'library-public', name: 'Public docs', is_default: false, source_count: 12, repos: [] },
    { id: 'library-support', name: 'Support playbook', is_default: false, source_count: 4, repos: [] },
]

const meta: Meta<typeof LearnedLibrariesSetting> = {
    title: 'Scenes-App/BusinessKnowledge/LearnedLibrariesSetting',
    component: LearnedLibrariesSetting,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        // Used by one settings section, so the story checks that it renders and adds no visual baseline.
        testOptions: {
            snapshotBrowsers: [],
            waitForSelector: '[data-attr=business-knowledge-learned-sources-library]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/business_knowledge/libraries/': libraries,
                '/api/projects/:team_id/business_knowledge/settings/': {
                    learn_from_support_enabled: true,
                    support_enabled: true,
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<typeof LearnedLibrariesSetting>

export const OneReceivingLibrary: Story = {}
