import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { useState } from 'react'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyDefinitionType } from '~/types'

import { PropertiesTable } from './PropertiesTable'

type AnyValue = string | number | boolean | null

function StatefulTable({ initial, onEditSpy }: { initial: AnyValue; onEditSpy: jest.Mock }): JSX.Element {
    const [value, setValue] = useState<AnyValue>(initial)
    return (
        <Provider>
            <PropertiesTable
                type={PropertyDefinitionType.Person}
                properties={{ custom_field: value }}
                rootKey="$set"
                onEdit={(key, newValue, oldValue) => {
                    onEditSpy(key, newValue, oldValue)
                    setValue(newValue)
                }}
            />
        </Provider>
    )
}

const renderStateful = (initial: AnyValue): { onEditSpy: jest.Mock; container: HTMLElement } => {
    const onEditSpy = jest.fn()
    const { container } = render(<StatefulTable initial={initial} onEditSpy={onEditSpy} />)
    return { onEditSpy, container }
}

const valueCell = (container: HTMLElement): HTMLElement => {
    const cell = container.querySelector('.properties-table-value') as HTMLElement | null
    if (!cell) {
        throw new Error('value cell not found')
    }
    return cell
}

const renderedValueText = (container: HTMLElement): string =>
    valueCell(container).querySelector('.editable')?.querySelector('span')?.textContent?.trim() ?? ''

const renderedTypeTag = (container: HTMLElement): string =>
    valueCell(container).querySelector('.LemonTag')?.textContent?.trim() ?? ''

const trigger = (container: HTMLElement): HTMLElement => valueCell(container).querySelector('.editable') as HTMLElement

const openTextEditor = (container: HTMLElement): HTMLInputElement => {
    fireEvent.click(trigger(container))
    return screen.getByRole('textbox') as HTMLInputElement
}

const openMenu = async (container: HTMLElement): Promise<void> => {
    fireEvent.click(trigger(container))
    await waitFor(() => expect(screen.getByText('Type as text…')).toBeInTheDocument())
}

const clickMenuItem = (label: string): void => {
    const item = screen.getAllByRole('menuitem').find((el) => el.textContent === label)
    if (!item) {
        throw new Error(`menu item "${label}" not found`)
    }
    fireEvent.click(item)
}

const typeAndSave = (input: HTMLInputElement, newText: string): void => {
    fireEvent.change(input, { target: { value: newText } })
    fireEvent.keyDown(input, { key: 'Enter' })
}

describe('PropertiesTable inline editor', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    describe('text editor', () => {
        it.each<[AnyValue, string, AnyValue, string]>([
            ['hello', 'world', 'world', 'string'],
            ['hello', '42', '42', 'string'],
            [42, '43', 43, 'number'],
            [42, 'hello', 'hello', 'string'],
        ])('%s → typing "%s" saves %s with type %s', (initial, typed, expectedValue, expectedTag) => {
            const { container, onEditSpy } = renderStateful(initial)
            typeAndSave(openTextEditor(container), typed)
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', expectedValue, initial)
            expect(renderedValueText(container)).toBe(String(expectedValue))
            expect(renderedTypeTag(container)).toBe(expectedTag)
        })

        it.each<[AnyValue]>([['hello'], [42]])('blurring without changes does not save (%s)', (initial) => {
            const { container, onEditSpy } = renderStateful(initial)
            const input = openTextEditor(container)
            fireEvent.change(input, { target: { value: 'something else' } })
            fireEvent.blur(input)
            expect(onEditSpy).not.toHaveBeenCalled()
        })
    })

    describe('bool/null menu', () => {
        it.each<[AnyValue, string, AnyValue, string]>([
            [null, 'true', true, 'boolean'],
            [null, 'false', false, 'boolean'],
            [true, 'false', false, 'boolean'],
            [true, 'null', null, 'null'],
            [false, 'true', true, 'boolean'],
            [false, 'null', null, 'null'],
        ])('%s → choosing %s saves %s with type %s', async (initial, label, expectedValue, expectedTag) => {
            const { container, onEditSpy } = renderStateful(initial)
            await openMenu(container)
            clickMenuItem(label)
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', expectedValue, initial)
            expect(renderedValueText(container)).toBe(label)
            expect(renderedTypeTag(container)).toBe(expectedTag)
        })

        it.each<[AnyValue, string]>([
            [null, 'null'],
            [true, 'true'],
            [false, 'false'],
        ])('choosing the same value (%s) does not save', async (initial, label) => {
            const { container, onEditSpy } = renderStateful(initial)
            await openMenu(container)
            clickMenuItem(label)
            expect(onEditSpy).not.toHaveBeenCalled()
        })
    })

    describe('Type as text… from bool/null', () => {
        it.each<[AnyValue]>([[null], [true], [false]])('input starts empty when initial is %s', async (initial) => {
            const { container } = renderStateful(initial)
            await openMenu(container)
            clickMenuItem('Type as text…')
            expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('')
        })

        it.each<[AnyValue, string, string, string]>([
            [null, 'world', 'world', 'string'],
            [true, 'world', 'world', 'string'],
            [false, 'world', 'world', 'string'],
            [null, 'true', 'true', 'string'],
            [true, 'true', 'true', 'string'],
            [null, '42', '42', 'string'],
        ])('%s → typing "%s" saves "%s" with type %s', async (initial, typed, expectedValue, expectedTag) => {
            const { container, onEditSpy } = renderStateful(initial)
            await openMenu(container)
            clickMenuItem('Type as text…')
            typeAndSave(screen.getByRole('textbox') as HTMLInputElement, typed)
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', expectedValue, initial)
            expect(renderedValueText(container)).toBe(expectedValue)
            expect(renderedTypeTag(container)).toBe(expectedTag)
        })
    })

    describe('editor mode follows the value type after a save', () => {
        it('string value → click → text editor (no menu)', () => {
            const { container } = renderStateful('hello')
            fireEvent.click(trigger(container))
            expect(screen.queryByText('Type as text…')).not.toBeInTheDocument()
            expect(screen.getByRole('textbox')).toBeInTheDocument()
        })

        it('null value → save string via Type as text → next click opens text editor', async () => {
            const { container } = renderStateful(null)
            await openMenu(container)
            clickMenuItem('Type as text…')
            typeAndSave(screen.getByRole('textbox') as HTMLInputElement, 'hello')
            fireEvent.click(trigger(container))
            expect(screen.queryByText('Type as text…')).not.toBeInTheDocument()
            expect(screen.getByRole('textbox')).toBeInTheDocument()
        })
    })

    describe('search by humanized label', () => {
        const renderSearchable = (type: PropertyDefinitionType): void => {
            render(
                <Provider>
                    <PropertiesTable type={type} properties={{ $geoip_city_name: 'London' }} searchable />
                </Provider>
            )
        }

        const search = (term: string): void => {
            fireEvent.change(screen.getByPlaceholderText('Search property keys and values'), {
                target: { value: term },
            })
        }

        it.each<[PropertyDefinitionType, string, string]>([
            [PropertyDefinitionType.Person, 'latest', 'Latest city name'],
            [PropertyDefinitionType.Event, 'city', 'City name'],
        ])('matches %s properties by their group label (%s → %s)', (type, term) => {
            renderSearchable(type)
            search(term)
            expect(screen.getByText('London')).toBeInTheDocument()
        })
    })

    describe('collapsible complex values', () => {
        const renderWith = (collapsible: boolean): ReturnType<typeof render> => {
            return render(
                <Provider>
                    <PropertiesTable
                        type={PropertyDefinitionType.Person}
                        properties={{ tags: ['a', 'b', 'c'] }}
                        collapsible={collapsible}
                    />
                </Provider>
            )
        }

        // The expanded array table renders an "array" type tag in its header; the collapsed
        // JSON viewer does not — so its absence is a reliable proxy for "not expanded".
        it.each([
            { collapsible: false, expectArrayTag: true },
            { collapsible: true, expectArrayTag: false },
        ])(
            'collapsible=$collapsible renders expanded array table: $expectArrayTag',
            ({ collapsible, expectArrayTag }) => {
                renderWith(collapsible)
                expect(!!screen.queryByText('array')).toBe(expectArrayTag)
            }
        )

        // Complex values render through JSONViewer, which unlike ValueDisplay applies no masking —
        // so the collapsed path must be wrapped in ph-no-capture to keep PII out of session replay.
        it('masks collapsed complex values from capture', () => {
            const { container } = renderWith(true)
            expect(container.querySelector('.ph-no-capture')).not.toBeNull()
        })
    })

    describe('empty state', () => {
        it('shows the generic message when there are no properties at all, even with a filter preference active', () => {
            // Regression: the "hide PostHog properties" preference is persisted and can be on
            // by default. It removed nothing here (there was nothing to remove), so the
            // "clear filters" prompt would be misleading.
            userPreferencesLogic.mount()
            userPreferencesLogic.actions.setHidePostHogPropertiesInTable(true)
            render(
                <Provider>
                    <PropertiesTable type={PropertyDefinitionType.Person} properties={{}} searchable filterable />
                </Provider>
            )
            expect(screen.getByText('No properties set yet')).toBeInTheDocument()
            expect(screen.queryByText('Clear filters')).not.toBeInTheDocument()
        })

        it('shows a clear-filters prompt only when a search term actually removed rows', () => {
            render(
                <Provider>
                    <PropertiesTable
                        type={PropertyDefinitionType.Person}
                        properties={{ email: 'a@b.com' }}
                        searchable
                    />
                </Provider>
            )
            fireEvent.change(screen.getByPlaceholderText('Search property keys and values'), {
                target: { value: 'no-match' },
            })
            expect(screen.getByText('No properties found')).toBeInTheDocument()
            expect(screen.getByText('Clear filters')).toBeInTheDocument()
        })

        it('lets a caller override the true-empty message (e.g. for a person with no profile)', () => {
            render(
                <Provider>
                    <PropertiesTable
                        type={PropertyDefinitionType.Person}
                        properties={{}}
                        emptyStateMessage="This distinct ID has no person profile"
                    />
                </Provider>
            )
            expect(screen.getByText('This distinct ID has no person profile')).toBeInTheDocument()
        })
    })

    describe('custom property key definitions', () => {
        it('gives a non-taxonomy property key click affordance once its definition loads from the team', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/property_definitions/': {
                        count: 1,
                        results: [
                            {
                                id: 'a',
                                name: 'referral_cost_usd',
                                description: 'Cost of the referral in USD',
                                type: PropertyDefinitionType.Person,
                            },
                        ],
                        next: undefined,
                    },
                },
            })
            propertyDefinitionsModel.mount()

            render(
                <Provider>
                    <PropertiesTable type={PropertyDefinitionType.Person} properties={{ referral_cost_usd: 12 }} />
                </Provider>
            )

            // Before the definition loads, the custom key has no popover affordance yet.
            expect(screen.getByText('referral_cost_usd').closest('.PropertyKeyInfo')).not.toHaveClass('cursor-pointer')

            await waitFor(() =>
                expect(screen.getByText('referral_cost_usd').closest('.PropertyKeyInfo')).toHaveClass('cursor-pointer')
            )
        })
    })
})
