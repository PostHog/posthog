import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { createPromptConfig, llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundVariablesLogic } from './llmPlaygroundVariablesLogic'

describe('llmPlaygroundVariablesLogic', () => {
    beforeEach(() => {
        initKeaTests()
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
