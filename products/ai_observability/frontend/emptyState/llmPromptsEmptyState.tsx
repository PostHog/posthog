import * as deskWizardPng from '@posthog/brand/hoggies/png/desk-wizard'
import { IconLlmPromptManagement } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LLMPromptPreview } from './LLMPromptPreview'
import { llmPromptsSetupLogic } from './llmPromptsSetupLogic'

const HedgehogDeskWizard = pngHoggie(deskWizardPng)

export const llmPromptsEmptyState: SceneProductEmptyState = {
    statusLogic: llmPromptsSetupLogic,
    config: {
        productKey: ProductKey.LLM_PROMPTS,
        productName: 'Prompt management',
        icon: <IconLlmPromptManagement />,
        accentColor: 'var(--color-product-llm-analytics-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogDeskWizard,
        text: {
            'needs-setup': {
                headline: 'Update prompts without redeploying',
                lead: 'Create and version LLM prompts in PostHog, then fetch them from your code at runtime. Every change becomes an immutable version you can compare, restore, and A/B test. Point a label like production at any version to control what your app serves, and move it whenever you want. Prompt management is free.',
            },
        },
        primaryAction: {
            label: 'Create your first prompt',
            to: urls.aiObservabilityPrompt('new'),
            accessControl: {
                resourceType: AccessControlResourceType.LlmAnalytics,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'new-prompt-button',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/prompt-management',
        previewLabel: 'Your prompts, once created',
        Preview: LLMPromptPreview,
    },
}
