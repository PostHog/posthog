import { z } from 'zod'

import { HogError } from '@/core/errors'
import type { PostHogApi } from '@/posthog/api'
import type { ProjectId } from '@/posthog/ids'

const PRESET_VALUE = '{value}'

const Preset = z.object({
    key: z.string(),
    label: z.string(),
    help_text: z.string(),
    conditions: z.record(z.string(), z.string()),
    takes_value: z.boolean(),
    placeholder: z.string(),
    default_value: z.string(),
})

export type Preset = z.output<typeof Preset>

const ProviderSettings = z.object({
    key: z.string(),
    name: z.string(),
    issuer: z.string(),
    docs_url: z.string(),
    condition_presets: z.array(Preset),
    required_presets: z.array(z.string()).default([]),
    setup_snippet: z.string(),
})

export type ProviderSettings = z.output<typeof ProviderSettings>

const ProvidersResponse = z.object({ supported: z.array(ProviderSettings) })

// PostHog keeps each provider's presets, rules and job snippet, so hog never carries a second copy.
export async function providerSettings(api: PostHogApi, projectId: ProjectId, key: string): Promise<ProviderSettings> {
    const { supported } = await api.get(
        `/api/projects/${projectId}/workload_trust_policy_requests/providers/`,
        ProvidersResponse
    )
    const settings = supported.find((provider) => provider.key === key)
    if (!settings) {
        throw new HogError(
            'unknown_provider',
            `This PostHog doesn't support the CI provider ${key} yet.`,
            'Check that the host runs a recent version of PostHog.'
        )
    }
    return settings
}

export function presetConditions(preset: Preset, value: string): Record<string, string> {
    return Object.fromEntries(
        Object.entries(preset.conditions).map(([claim, template]) => [
            claim,
            template.replace(PRESET_VALUE, () => value),
        ])
    )
}

export function requiredPresets(settings: ProviderSettings): Preset[] {
    return settings.condition_presets.filter((preset) => settings.required_presets.includes(preset.key))
}
