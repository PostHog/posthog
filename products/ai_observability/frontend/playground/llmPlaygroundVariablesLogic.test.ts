import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { createPromptConfig, llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundVariablesLogic } from './llmPlaygroundVariablesLogic'

describe('llmPlaygroundVariablesLogic', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [{ id: 'key-s1', provider: 'system_one', name: 'System One', state: 'ok' }],
                },
                '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
                '/api/llm_proxy/models/': ({ request }) => [
                    200,
                    new URL(request.url).searchParams.get('provider_key_id')
                        ? [{ id: 'jev-1', name: 'jev-1', provider: 'System One', supports_chat: false }]
                        : [{ id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' }],
                ],
                '/api/projects/:team_id/llm_analytics/provider_keys/:key_id/models/': ({ params }) => [
                    200,
                    params.key_id
                        ? [{ id: 'jev-1', name: 'jev-1', provider: 'System One', supports_chat: false }]
                        : [{ id: 'gpt-5-mini', name: 'GPT-5 Mini', provider: 'OpenAI', description: '' }],
                ],
            },
        })
    })

    it('detects only the texts a System One panel sends', async () => {
        const logic = llmPlaygroundVariablesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        llmPlaygroundPromptsLogic.actions.setMessages([{ role: 'user', content: 'Hidden {{message_only}}' }])
        llmPlaygroundPromptsLogic.actions.setModel('jev-1', 'key-s1')
        llmPlaygroundPromptsLogic.actions.setDecisionInput('About {{topic}}')
        llmPlaygroundPromptsLogic.actions.setDecisionQuestions([
            { id: 'q1', type: 'noul', instructions: 'Is {{tone}} kind?', options: [] },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.detectedVariables).toEqual(['topic', 'tone'])

        logic.unmount()
    })

    it('detects variables across all comparison panels and shares values by name', async () => {
        // Detection that only reads the active panel would hide panel 2's variables,
        // and per-panel values would break the "fill {{topic}} once" comparison flow.
        const logic = llmPlaygroundVariablesLogic()
        logic.mount()

        llmPlaygroundPromptsLogic.actions.setPromptConfigs([
            createPromptConfig({
                systemPrompt: 'Answer about {{topic}}.',
                messages: [{ role: 'user', content: '{{question}}' }],
            }),
            createPromptConfig({ systemPrompt: 'Be {{tone}} about {{topic}}.', messages: [] }),
        ])

        await expectLogic(logic).toMatchValues({
            detectedVariables: ['topic', 'question', 'tone'],
            unfilledVariables: ['topic', 'question', 'tone'],
        })

        logic.actions.setVariableValue('topic', 'penguins')

        await expectLogic(logic).toMatchValues({
            unfilledVariables: ['question', 'tone'],
        })

        logic.unmount()
    })

    it('clears values when a new source loads into the playground', async () => {
        // Without this, loading a different saved prompt that reuses a variable
        // name silently sends the previous prompt's value.
        const logic = llmPlaygroundVariablesLogic()
        logic.mount()

        logic.actions.setVariableValue('topic', 'penguins')
        llmPlaygroundPromptsLogic.actions.setupPlaygroundFromEvent({})

        await expectLogic(logic).toMatchValues({ variableValues: {} })

        logic.unmount()
    })
})
