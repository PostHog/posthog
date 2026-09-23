import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { GroupTypeIndex, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

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
                '/api/event/values': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
                '/api/environments/:team/events/values': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
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

        // Wait for options to load and appear (300ms debounce + async fetch needs headroom under CI load)
        await waitFor(
            () => {
                expect(screen.getByText('Chrome')).toBeInTheDocument()
            },
            { timeout: 3000 }
        )

        const callCountAfterLoad = loadPropertyValuesSpy.mock.calls.length

        // Select a value from the dropdown
        userEvent.click(screen.getByText('Chrome'))
        // Flush pending microtasks so any async loadPropertyValues calls settle before we assert
        await new Promise((r) => setTimeout(r, 0))

        // loadPropertyValues should not have been called again
        expect(loadPropertyValuesSpy.mock.calls.length).toBe(callCountAfterLoad)
    })

    it('renders with showInlineValidationErrors prop', () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="test_prop"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                    validationError="Test validation error"
                    showInlineValidationErrors
                />
            </Provider>
        )

        // Check that the error message is displayed when showInlineValidationErrors is true
        expect(screen.getByText('Test validation error')).toBeInTheDocument()
    })

    it('displays validation error messages', async () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="test"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                    validationError="This is a test error"
                    showInlineValidationErrors
                />
            </Provider>
        )

        // Check that the error message is displayed
        expect(screen.getByText('This is a test error')).toBeInTheDocument()

        // Check that the error container has the danger class
        const errorContainer = screen.getByText('This is a test error').closest('div')
        expect(errorContainer).toHaveClass('text-danger')
    })

    it('allows regex input for numeric properties', async () => {
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/userId': {
                id: 'userId',
                name: 'userId',
                property_type: PropertyType.Numeric,
                is_numerical: true,
                is_seen_on_filtered_events: false,
            },
        })

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="userId"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Regex}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.type(input, 'user.*7$')

        expect(input).toHaveValue('user.*7$')
    })

    it.each([
        {
            label: 'trims surrounding whitespace from a pasted value before committing it',
            propertyKey: '$ai_trace_id',
            operator: PropertyOperator.Exact,
            pastedValue: ' 9c8a6265-382a-4972-9640-b400dabdd83e ',
            expectedArg: ['9c8a6265-382a-4972-9640-b400dabdd83e'],
        },
        {
            label: 'preserves surrounding whitespace for regex operators, where it can be meaningful',
            propertyKey: '$current_url',
            operator: PropertyOperator.Regex,
            pastedValue: 'foo ',
            expectedArg: 'foo ',
        },
        {
            label: 'preserves surrounding whitespace on a value picked from the suggestion list',
            propertyKey: 'name',
            operator: PropertyOperator.Exact,
            suggestedValue: 'Acme Corp ',
            expectedArg: ['Acme Corp '],
        },
    ])('$label', async ({ propertyKey, operator, pastedValue, suggestedValue, expectedArg }) => {
        if (suggestedValue) {
            const values = { results: [{ name: suggestedValue }], refreshing: false }
            useMocks({
                get: {
                    '/api/event/values': values,
                    '/api/environments/:team/events/values': values,
                },
            })
        }

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey={propertyKey}
                    type={PropertyFilterType.Event}
                    operator={operator}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const user = userEvent.setup()
        const input = screen.getByRole('textbox')
        await user.click(input)
        if (suggestedValue) {
            // The default matcher trims, so this finds the option by its visible label
            const option = await screen.findByText(suggestedValue.trim(), undefined, { timeout: 3000 })
            await user.click(option)
        } else {
            await user.paste(pastedValue)
            await user.keyboard('{Enter}')
        }

        await waitFor(() => {
            expect(onSet).toHaveBeenCalledWith(expectedArg)
        })
    })

    it('preserves whitespace on a value picked from search results the dropdown still shows', async () => {
        // After the first pick the dropdown keeps rendering the search results, while the component
        // reloads the unsearched values behind it. The second pick then arrives from a list the
        // component no longer holds.
        const searchResults = { results: [{ name: 'Acme Corp ' }, { name: 'Acme Inc ' }], refreshing: false }
        const unsearchedResults = { results: [{ name: 'Chrome' }], refreshing: false }
        const respondToSearch = ({ request }: { request: Request }): typeof searchResults =>
            new URL(request.url).searchParams.get('value') ? searchResults : unsearchedResults
        useMocks({
            get: {
                '/api/event/values': respondToSearch,
                '/api/environments/:team/events/values': respondToSearch,
            },
        })

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="name"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const user = userEvent.setup()
        await user.type(screen.getByRole('textbox'), 'Acme')

        // The default matcher trims, so this finds the option by its visible label
        await user.click(await screen.findByText('Acme Corp', undefined, { timeout: 3000 }))

        // The pick clears the search, so the unsearched values replace the ones just searched
        await waitFor(
            () => {
                expect(propertyDefinitionsModel.values.options['name']?.values).toEqual([{ name: 'Chrome' }])
            },
            { timeout: 3000 }
        )

        await user.click(screen.getByText('Acme Inc'))

        await waitFor(() => {
            expect(onSet).toHaveBeenLastCalledWith(['Acme Inc '])
        })
    })

    it('trims a typed value that only the previous property offered', async () => {
        // Some callers change `propertyKey` without remounting the editor. The values offered for
        // the previous property must not count as suggestions of the new one, or a value the user
        // types for the new property keeps whitespace that only a suggestion may keep.
        const valuesForKey: Record<string, { results: { name: string }[]; refreshing: boolean }> = {
            company_name: { results: [{ name: 'Acme Corp ' }], refreshing: false },
            city: { results: [{ name: 'Springfield' }], refreshing: false },
        }
        const respondToKey = ({ request }: { request: Request }): (typeof valuesForKey)[string] =>
            valuesForKey[new URL(request.url).searchParams.get('key') ?? ''] ?? { results: [], refreshing: false }
        useMocks({
            get: {
                '/api/event/values': respondToKey,
                '/api/environments/:team/events/values': respondToKey,
            },
        })

        const onSet = jest.fn()
        const editor = (propertyKey: string): JSX.Element => (
            <Provider>
                <PropertyValue
                    propertyKey={propertyKey}
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const { rerender } = render(editor('company_name'))
        const user = userEvent.setup()
        await user.click(screen.getByRole('textbox'))
        // The default matcher trims, so this finds the option by its visible label
        await screen.findByText('Acme Corp', undefined, { timeout: 3000 })

        rerender(editor('city'))
        await screen.findByText('Springfield', undefined, { timeout: 3000 })

        await user.click(screen.getByRole('textbox'))
        await user.paste('Acme Corp ')
        await user.keyboard('{Enter}')

        await waitFor(() => {
            expect(onSet).toHaveBeenLastCalledWith(['Acme Corp'])
        })
    })

    it('allows text when a polymorphic property overrides a globally inferred numeric type', async () => {
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/current_value': {
                id: 'current_value',
                name: 'current_value',
                property_type: PropertyType.Numeric,
                is_numerical: true,
                is_seen_on_filtered_events: false,
            },
        })

        render(
            <Provider>
                <PropertyValue
                    propertyKey="current_value"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={jest.fn()}
                    value={[]}
                    propertyTypeOverride={PropertyType.String}
                    staticValues={[]}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.type(input, 'enterprise')

        expect(input).toHaveValue('enterprise')
        expect(loadPropertyValuesSpy).not.toHaveBeenCalled()
    })

    it('keeps numeric-only input for non-regex numeric properties', async () => {
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/userId': {
                id: 'userId',
                name: 'userId',
                property_type: PropertyType.Numeric,
                is_numerical: true,
                is_seen_on_filtered_events: false,
            },
        })

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="userId"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.type(input, '7a.8$')

        expect(input).toHaveValue('7.8')
    })

    it('renders static values without fetching from the API', async () => {
        // Guards the staticValues escape hatch: consumers whose events are not in
        // ClickHouse (e.g. internal events) must get their statically known values,
        // not values of same-named properties fetched from the events table.
        render(
            <Provider>
                <PropertyValue
                    propertyKey="scope"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={jest.fn()}
                    value={[]}
                    staticValues={[{ name: 'FeatureFlag' }, { name: 'Insight' }]}
                />
            </Provider>
        )

        userEvent.click(screen.getByRole('textbox'))

        expect(await screen.findByText('FeatureFlag')).toBeInTheDocument()
        expect(screen.getByText('Insight')).toBeInTheDocument()

        // Flush the load debounce window to catch a stray fetch
        await new Promise((r) => setTimeout(r, 350))
        expect(loadPropertyValuesSpy).not.toHaveBeenCalled()
    })

    it('renders a group `id` filter with the generic value editor, not the group-name picker', () => {
        // Reverting the editor swap for `id` is the regression fix: a group property
        // named `id` must keep its normal value input (GroupKeySelect, used only for
        // the true `$group_key` identity, would replace it with a group search).
        render(
            <Provider>
                <PropertyValue
                    propertyKey="id"
                    type={PropertyFilterType.Group}
                    groupTypeIndex={0 as GroupTypeIndex}
                    operator={PropertyOperator.Exact}
                    onSet={jest.fn()}
                    value={['org-abc-123']}
                />
            </Provider>
        )

        // GroupKeySelect's distinctive placeholder is absent — the generic editor is used.
        expect(screen.queryByPlaceholderText('Search groups by name...')).not.toBeInTheDocument()
        // The pasted id is shown as the value.
        expect(screen.getByText('org-abc-123')).toBeInTheDocument()
    })
})
