import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { PropertyValue } from './PropertyValue'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('PropertyValue', () => {
    let loadPropertyValuesSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/event/values': [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                '/api/environments/:team/events/values': [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
            },
        })
        initKeaTests()
        propertyDefinitionsModel.mount()
        loadPropertyValuesSpy = jest.spyOn(propertyDefinitionsModel.actions, 'loadPropertyValues')
    })

    afterEach(() => {
        cleanup()
    })

    it('does not re-fetch property values when selecting a value from the dropdown', async () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="$browser"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        // Focus the input to open the dropdown
        const input = screen.getByRole('textbox')
        userEvent.click(input)

        // Wait for options to load and appear
        await waitFor(() => {
            expect(screen.getByText('Chrome')).toBeInTheDocument()
        })

        const callCountAfterLoad = loadPropertyValuesSpy.mock.calls.length

        // Select a value from the dropdown
        userEvent.click(screen.getByText('Chrome'))
        // Flush pending microtasks so any async loadPropertyValues calls settle before we assert
        await new Promise((r) => setTimeout(r, 0))

        // loadPropertyValues should not have been called again
        expect(loadPropertyValuesSpy.mock.calls.length).toBe(callCountAfterLoad)
    })
})
