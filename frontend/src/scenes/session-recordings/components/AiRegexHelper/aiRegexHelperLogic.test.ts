import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { aiRegexHelperLogic } from './aiRegexHelperLogic'

describe('aiRegexHelperLogic', () => {
    let logic: ReturnType<typeof aiRegexHelperLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = aiRegexHelperLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('stores the generated regex on success', async () => {
        jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({
            result: 'success',
            data: { output: '^/auth/.*$' },
        })

        logic.actions.setInput('urls under /auth')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ generatedRegex: '^/auth/.*$', error: '', isLoading: false })
    })

    it('surfaces the model error message on a result-error response', async () => {
        jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({
            result: 'error',
            data: { output: 'Please ask questions only about regex generation.' },
        })

        logic.actions.setInput('what is the weather?')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({
            error: 'Please ask questions only about regex generation.',
            generatedRegex: '',
        })
    })

    it('surfaces the server-provided detail when the request throws an ApiError', async () => {
        jest.spyOn(api.recordings, 'aiRegex').mockRejectedValue(
            new ApiError('Invalid response from OpenAI', 400, undefined, {
                detail: 'Invalid response from OpenAI',
            })
        )

        logic.actions.setInput('something')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ error: 'Invalid response from OpenAI', isLoading: false })
    })

    it('falls back to a generic message for non-ApiError failures', async () => {
        jest.spyOn(api.recordings, 'aiRegex').mockRejectedValue(new Error('network down'))

        logic.actions.setInput('something')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ error: 'Failed to generate regex. Try again?', isLoading: false })
    })

    it('falls back to a generic message for an unrecognised response shape', async () => {
        jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({} as any)

        logic.actions.setInput('something')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ error: 'Failed to generate regex. Try again?' })
    })
})
