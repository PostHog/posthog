import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { aiRegexHelperLogic } from './aiRegexHelperLogic'

const GENERIC_ERROR = 'Failed to generate regex. Try again?'

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

    const errorCases: {
        name: string
        mock: () => void
        expectedError: string
    }[] = [
        {
            name: 'surfaces the model error message on a result-error response',
            mock: () =>
                jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({
                    result: 'error',
                    data: { output: 'Please ask questions only about regex generation.' },
                }),
            expectedError: 'Please ask questions only about regex generation.',
        },
        {
            name: 'surfaces the server-provided detail when the request throws an ApiError',
            mock: () =>
                jest.spyOn(api.recordings, 'aiRegex').mockRejectedValue(
                    new ApiError('Invalid response from OpenAI', 400, undefined, {
                        detail: 'Invalid response from OpenAI',
                    })
                ),
            expectedError: 'Invalid response from OpenAI',
        },
        {
            name: 'falls back to a generic message for non-ApiError failures',
            mock: () => jest.spyOn(api.recordings, 'aiRegex').mockRejectedValue(new Error('network down')),
            expectedError: GENERIC_ERROR,
        },
        {
            name: 'falls back to a generic message for an unrecognised response shape',
            mock: () => jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({} as any),
            expectedError: GENERIC_ERROR,
        },
        {
            name: 'falls back to a generic message for a success response missing output',
            mock: () => jest.spyOn(api.recordings, 'aiRegex').mockResolvedValue({ result: 'success' } as any),
            expectedError: GENERIC_ERROR,
        },
    ]

    it.each(errorCases)('$name', async ({ mock, expectedError }) => {
        mock()

        logic.actions.setInput('something')
        await expectLogic(logic, () => logic.actions.handleGenerateRegex()).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ error: expectedError, generatedRegex: '', isLoading: false })
    })
})
