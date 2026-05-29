import { LLM_PROVIDER_SELECT_OPTIONS } from './LLMProviderIcon'
import { LLM_PROVIDER_LABELS } from './settings/llmProviderKeysLogic'

describe('LLM_PROVIDER_SELECT_OPTIONS', () => {
    it('should have an entry for every provider in LLM_PROVIDER_LABELS', () => {
        const providers = Object.keys(LLM_PROVIDER_LABELS)
        expect(LLM_PROVIDER_SELECT_OPTIONS.map((o) => o.value)).toEqual(providers)
        for (const option of LLM_PROVIDER_SELECT_OPTIONS) {
            expect(option.label).toBe(LLM_PROVIDER_LABELS[option.value])
            expect(option.icon).toBeTruthy()
        }
    })
})
