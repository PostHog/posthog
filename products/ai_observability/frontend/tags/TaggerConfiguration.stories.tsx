import type { Meta, StoryObj } from '@storybook/react'

import { PropertyFilterType, PropertyOperator } from '~/types'

import type { TaggerApi } from '../generated/api.schemas'
import { TaggerConfiguration } from './TaggerConfiguration'

const baseTagger: TaggerApi = {
    id: '0190b1f2-0000-0000-0000-000000000002',
    name: 'Support topics',
    description: 'Tags support conversations by topic',
    enabled: false,
    tagger_type: 'llm',
    tagger_config: {
        prompt: 'Which support topics does this generation cover?',
        tags: [
            { name: 'billing', description: 'Invoices, refunds, and plan changes' },
            { name: 'login', description: 'Sign-in and password problems' },
        ],
        min_tags: 0,
        max_tags: 2,
    },
    conditions: [
        {
            id: 'cond-1',
            rollout_percentage: 25,
            properties: [
                {
                    key: '$ai_model',
                    value: 'gpt-5-mini',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        },
        { id: 'cond-2', rollout_percentage: 100, properties: [] },
    ],
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: '0190b1f2-0000-0000-0000-000000000003',
        provider_key_name: 'Production key',
    },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: {
        id: 1,
        uuid: '0190b1f2-0000-0000-0000-000000000004',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    deleted: false,
    migrated_to_evaluation_id: null,
}

const meta: Meta<typeof TaggerConfiguration> = {
    title: 'Scenes-App/LLM observability/Tagger configuration',
    component: TaggerConfiguration,
    parameters: {
        viewMode: 'story',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof TaggerConfiguration>

export const LLMTagger: Story = { args: { tagger: baseTagger } }

export const HogTagger: Story = {
    args: {
        tagger: {
            ...baseTagger,
            name: 'Billing keywords',
            tagger_type: 'hog',
            tagger_config: { source: "return output ilike '%invoice%' ? ['billing'] : []", tags: [] },
            model_configuration: null,
            conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
        },
    },
}
