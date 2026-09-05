import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { accountDetailViewsLogic } from '../accountDetailViewsLogic'
import { AddViewDialog } from './AddViewDialog'

const VIEWS_ENDPOINT = '/api/environments/:team_id/column_configurations/'

describe('AddViewDialog', () => {
    let logic: ReturnType<typeof accountDetailViewsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({ get: { [VIEWS_ENDPOINT]: { count: 0, results: [] } } })
        initKeaTests()
        logic = accountDetailViewsLogic()
        logic.mount()
        logic.actions.setAddViewOpen(true)
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
        localStorage.clear()
    })

    it('keeps widgets as an array when a checkbox changes', () => {
        render(
            <Provider>
                <AddViewDialog />
            </Provider>
        )

        const textCheckbox = screen.getByText('Text').closest('.LemonCheckbox')?.querySelector('input')
        expect(textCheckbox).toBeInTheDocument()

        fireEvent.click(textCheckbox as HTMLInputElement)

        expect(logic.values.newViewForm.widgets).toEqual(['summary', 'text'])
    })
})
