import React from 'react'
import { PropertyNamesSelect } from './PropertyNamesSelect'
import { render, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { initKeaTestLogic } from '~/test/init'
import { Provider } from 'kea'

initKeaTestLogic()

test('Can load, deselect property, hide popup and receive selection via onChange', async () => {
    const properties = ['Property A', 'Property B', 'Property C']
    const onChange = jest.fn()
    const { findByRole } = render(
        <Provider>
            <PropertyNamesSelect onChange={onChange} allProperties={properties} />
        </Provider>
    )

    const combo = await findByRole('combobox')
    const summaryText = await within(combo).findByText(/0 of 3/)
    userEvent.click(summaryText)

    const propertyACheckbox = await findByRole('checkbox', { name: 'Property A' })
    userEvent.click(propertyACheckbox)

    userEvent.click(summaryText)

    expect(onChange).toHaveBeenLastCalledWith(['Property A'])
})

test('Can load, deselect property, click away and receive selection via onChange', async () => {
    const properties = ['Property A', 'Property B', 'Property C']

    const onChange = jest.fn()

    const { findByRole } = render(
        <Provider>
            <PropertyNamesSelect onChange={onChange} allProperties={properties} />
        </Provider>
    )
    const combo = await findByRole('combobox')
    const summaryText = await within(combo).findByText(/0 of 3/)
    userEvent.click(summaryText)

    const propertyACheckbox = await findByRole('checkbox', { name: 'Property A' })
    userEvent.click(propertyACheckbox)

    // Click outside the component
    userEvent.click(document.body)

    expect(onChange).toHaveBeenLastCalledWith(['Property A'])
})

test('Can load, deselect and select all, and receive selection via onChange', async () => {
    const properties = ['Property A', 'Property B', 'Property C']

    const onChange = jest.fn()

    const { findByRole } = render(
        <Provider>
            <PropertyNamesSelect onChange={onChange} allProperties={properties} />
        </Provider>
    )
    const combo = await findByRole('combobox')
    await within(combo).findByText(/0 of 3/)

    const selectAllCheckbox = await findByRole('checkbox', { name: 'Select all' })
    userEvent.click(selectAllCheckbox)
    await within(combo).findByText(/3 of 3/)

    expect(onChange).toHaveBeenLastCalledWith(['Property A', 'Property B', 'Property C'])

    userEvent.click(selectAllCheckbox)
    await within(combo).findByText(/0 of 3/)
    expect(onChange).toHaveBeenLastCalledWith([])
})

test('Can filter properties by case insensitive substring match', async () => {
    const properties = ['Property A', 'Property B', 'Property C']

    const onChange = jest.fn()

    const { findByRole, queryByRole } = render(
        <Provider>
            <PropertyNamesSelect onChange={onChange} allProperties={properties} />
        </Provider>
    )

    const combo = await findByRole('combobox')
    const summaryText = await within(combo).findByText(/0 of 3/)
    userEvent.click(summaryText)

    await findByRole('checkbox', { name: /Property B/ })
    const searchBox = await findByRole('textbox')
    userEvent.type(searchBox, 'property a')

    await waitFor(() => expect(queryByRole('checkbox', { name: /Property B/ })).toBeNull())
})
