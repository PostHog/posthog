import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { LLMProviderIcon, LLM_PROVIDER_SELECT_OPTIONS } from './LLMProviderIcon'
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

    it('shows a generic icon for System One', () => {
        expect(LLM_PROVIDER_LABELS.system_one).toBe('System One')
        expect(renderToStaticMarkup(createElement(LLMProviderIcon, { provider: 'system_one' }))).toContain('<svg')
    })
})
