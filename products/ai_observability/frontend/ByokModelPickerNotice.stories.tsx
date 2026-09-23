import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'

import { useStorybookMocks } from '~/mocks/browser'

import { ByokModelPickerNotice } from './ByokModelPickerNotice'
import { getModelPickerFooterLink, ModelPicker } from './ModelPicker'
import { modelPickerLogic } from './modelPickerLogic'
import { LLMProviderKey, LLMProviderKeyState } from './settings/llmProviderKeysLogic'

interface StoryArgs {
    keyState: LLMProviderKeyState | null
    modelsFail: boolean
}

function providerKey(state: LLMProviderKeyState): Partial<LLMProviderKey> {
    return { id: 'key-1', provider: 'openai', name: 'Production', state }
}

function PickerWithNotice(): JSX.Element {
    const { providerModelGroups, hasByokKeys, byokModelsLoading, providerKeysLoading } = useValues(modelPickerLogic)

    return (
        // The story root has no width of its own, so the picker column is sized here to match the form it sits in.
        <div className="w-[560px]">
            <ModelPicker
                model=""
                selectedProviderKeyId={null}
                onSelect={() => {}}
                groups={providerModelGroups}
                loading={byokModelsLoading || providerKeysLoading}
                footerLink={getModelPickerFooterLink(hasByokKeys)}
            />
            <ByokModelPickerNotice />
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-App/AI observability/BYOK model picker notice',
    render: ({ keyState, modelsFail }) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: keyState ? [providerKey(keyState)] : [],
                },
                '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
                // Only the per-key request fails. The playground list uses the same path without a key id.
                '/api/llm_proxy/models/': ({ request }) =>
                    modelsFail && new URL(request.url).searchParams.get('provider_key_id')
                        ? [500, { error: 'Internal error' }]
                        : [200, []],
            },
        })

        return <PickerWithNotice />
    },
}
export default meta

export const NoProviderKeys: StoryObj<StoryArgs> = {
    args: { keyState: null, modelsFail: false },
}

export const NoUsableProviderKeys: StoryObj<StoryArgs> = {
    args: { keyState: 'invalid', modelsFail: false },
}

export const ModelsFailedToLoad: StoryObj<StoryArgs> = {
    args: { keyState: 'ok', modelsFail: true },
}
