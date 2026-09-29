import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SceneTags } from './SceneTags'

describe('SceneTags', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team/tags': [] } })
        initKeaTests()
    })
    afterEach(() => cleanup())

    it.each([
        { saving: false, suggestCalls: 1 },
        { saving: true, suggestCalls: 0 },
    ])(
        'keeps a typed tag and asks for suggestions only when no tag save is running (saving: $saving)',
        async ({ saving, suggestCalls }) => {
            const onSave = jest.fn()
            const onSuggest = jest.fn()
            render(
                <Provider>
                    <SceneTags dataAttrKey="insight" tags={[]} onSave={onSave} onSuggest={onSuggest} loading={saving} />
                </Provider>
            )

            await userEvent.click(screen.getByText('Click to add tags'))
            expect(screen.getByPlaceholderText('try "official"')).toHaveFocus()
            await userEvent.keyboard('growth')
            await userEvent.click(screen.getByLabelText('Suggest tags'))

            expect(onSave).toHaveBeenCalledWith(['growth'])
            expect(onSuggest).toHaveBeenCalledTimes(suggestCalls)
        }
    )
})
