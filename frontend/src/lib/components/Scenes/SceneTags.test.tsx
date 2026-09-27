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

    it('keeps a tag typed into the editor when the person asks for suggestions', async () => {
        const onSave = jest.fn()
        const onSuggest = jest.fn()
        render(
            <Provider>
                <SceneTags dataAttrKey="insight" tags={[]} onSave={onSave} onSuggest={onSuggest} />
            </Provider>
        )

        await userEvent.click(screen.getByText('Click to add tags'))
        expect(screen.getByPlaceholderText('try "official"')).toHaveFocus()
        await userEvent.keyboard('growth')
        await userEvent.click(screen.getByLabelText('Suggest tags'))

        expect(onSave).toHaveBeenCalledWith(['growth'])
        expect(onSuggest).toHaveBeenCalledTimes(1)
    })
})
