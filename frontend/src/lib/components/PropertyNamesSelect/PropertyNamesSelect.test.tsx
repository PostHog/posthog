import React from 'react'
import { PropertyNamesSelect } from './PropertyNamesSelect'
import { render, within } from '@testing-library/react'
import { setupServer } from 'msw/node'
import userEvent from '@testing-library/user-event'
import { GetPersonPropertiesRequest, GetPersonPropertiesResponse } from 'lib/api/person-properties'
import { ResponseResolver, RestRequest, RestContext, rest } from 'msw'

test('Can load, deselect property, hide popup and receive selection via onChange', async () => {
    const server = setupServer(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },
                ])
            )
        )
    )
    server.listen()

    const onChange = jest.fn()
    const { findByRole } = render(<PropertyNamesSelect onChange={onChange} />)

    const combo = await findByRole('combobox')
    const summaryText = await within(combo).findByText(/3 of 3 selected/)
    userEvent.click(summaryText)

    const propertyACheckbox = await findByRole('checkbox', { name: 'Property A' })
    userEvent.click(propertyACheckbox)

    userEvent.click(summaryText)

    expect(onChange).toHaveBeenLastCalledWith(['Property B', 'Property C'])
})

test('Can load, deselect property, click away and receive selection via onChange', async () => {
    const server = setupServer(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },
                ])
            )
        )
    )
    server.listen()

    const onChange = jest.fn()
    const { findByRole } = render(<PropertyNamesSelect onChange={onChange} />)

    const combo = await findByRole('combobox')
    const summaryText = await within(combo).findByText(/3 of 3 selected/)
    userEvent.click(summaryText)

    const propertyACheckbox = await findByRole('checkbox', { name: 'Property A' })
    userEvent.click(propertyACheckbox)

    // Click outside the component
    userEvent.click(document.body)

    expect(onChange).toHaveBeenLastCalledWith(['Property B', 'Property C'])
})

test('Can load, deselect and select all, and receive selection via onChange', async () => {
    const server = setupServer(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },
                ])
            )
        )
    )
    server.listen()

    const onChange = jest.fn()
    const { findByRole } = render(<PropertyNamesSelect onChange={onChange} />)

    const combo = await findByRole('combobox')
    await within(combo).findByText(/3 of 3 selected/)

    const selectAllCheckbox = await findByRole('checkbox', { name: 'Select all' })
    userEvent.click(selectAllCheckbox)
    await within(combo).findByText(/0 of 3 selected/)

    expect(onChange).toHaveBeenLastCalledWith([])

    userEvent.click(selectAllCheckbox)
    await within(combo).findByText(/3 of 3 selected/)
    expect(onChange).toHaveBeenLastCalledWith(['Property A', 'Property B', 'Property C'])
})

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
const mockGetPersonProperties = (
    handler: ResponseResolver<RestRequest<GetPersonPropertiesRequest, any>, RestContext, GetPersonPropertiesResponse>
) => rest.get<GetPersonPropertiesRequest, GetPersonPropertiesResponse>('/api/person/properties', handler)
