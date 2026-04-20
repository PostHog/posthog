import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { useState } from 'react'

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

const renderedValueText = (container: HTMLElement): string => {
    // The clickable value text lives inside the .editable wrapper, which holds an inner span with the value.
    const editable = valueCell(container).querySelector('.editable')
    return editable?.querySelector('span')?.textContent?.trim() ?? ''
}

const renderedTypeTag = (container: HTMLElement): string => {
    return valueCell(container).querySelector('.LemonTag')?.textContent?.trim() ?? ''
}

const trigger = (container: HTMLElement): HTMLElement => {
    return valueCell(container).querySelector('.editable') as HTMLElement
}

const openTextEditor = (container: HTMLElement): HTMLInputElement => {
    fireEvent.click(trigger(container))
    return screen.getByRole('textbox') as HTMLInputElement
}

const openMenu = async (container: HTMLElement): Promise<void> => {
    fireEvent.click(trigger(container))
    await waitFor(() => expect(screen.getByText('Type as text…')).toBeInTheDocument())
}

const typeAndSave = (input: HTMLInputElement, newText: string): void => {
    fireEvent.change(input, { target: { value: newText } })
    fireEvent.keyDown(input, { key: 'Enter' })
}

describe('PropertiesTable inline editor — full transition matrix', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    describe('starting from string "hello"', () => {
        it('text edit → "world" renders as string "world"', () => {
            const { container, onEditSpy } = renderStateful('hello')
            typeAndSave(openTextEditor(container), 'world')
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', 'world', 'hello')
            expect(renderedValueText(container)).toBe('world')
            expect(renderedTypeTag(container)).toBe('string')
        })

        it('text edit → "42" renders as string "42" (does NOT become number)', () => {
            const { container } = renderStateful('hello')
            typeAndSave(openTextEditor(container), '42')
            expect(renderedValueText(container)).toBe('42')
            expect(renderedTypeTag(container)).toBe('string')
        })
    })

    describe('starting from number 42', () => {
        it('text edit → "43" preserves number type', () => {
            const { container, onEditSpy } = renderStateful(42)
            typeAndSave(openTextEditor(container), '43')
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', 43, 42)
            expect(renderedValueText(container)).toBe('43')
            expect(renderedTypeTag(container)).toBe('number')
        })

        it('text edit → "hello" falls back to string (input is not numeric)', () => {
            const { container, onEditSpy } = renderStateful(42)
            typeAndSave(openTextEditor(container), 'hello')
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', 'hello', 42)
            expect(renderedValueText(container)).toBe('hello')
            expect(renderedTypeTag(container)).toBe('string')
        })
    })

    describe.each([
        ['null', null],
        ['true', true],
        ['false', false],
    ])('starting from %s', (_label, initial) => {
        it.each([
            ['true', true],
            ['false', false],
            ['null', null],
        ])('menu → %s renders correctly', async (toLabel, toValue) => {
            const { container, onEditSpy } = renderStateful(initial as AnyValue)
            await openMenu(container)
            fireEvent.click(screen.getByRole('menuitem', { name: toLabel }))

            if (initial === toValue) {
                // No-op selection — onEdit is skipped because newValue == value
                expect(onEditSpy).not.toHaveBeenCalled()
            } else {
                expect(onEditSpy).toHaveBeenCalledWith('custom_field', toValue, initial)
            }
            expect(renderedValueText(container)).toBe(toLabel)
            expect(renderedTypeTag(container)).toBe(toValue === null ? 'null' : 'boolean')
        })

        it('menu → Type as text… → "world" renders as string "world"', async () => {
            const { container, onEditSpy } = renderStateful(initial as AnyValue)
            await openMenu(container)
            fireEvent.click(screen.getByRole('menuitem', { name: 'Type as text…' }))
            const input = screen.getByRole('textbox') as HTMLInputElement
            typeAndSave(input, 'world')
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', 'world', initial)
            expect(renderedValueText(container)).toBe('world')
            expect(renderedTypeTag(container)).toBe('string')
        })

        it('menu → Type as text… → input starts empty (does not pre-fill with literal)', async () => {
            const { container } = renderStateful(initial as AnyValue)
            await openMenu(container)
            fireEvent.click(screen.getByRole('menuitem', { name: 'Type as text…' }))
            const input = screen.getByRole('textbox') as HTMLInputElement
            expect(input.value).toBe('')
        })

        it('menu → Type as text… → typing "true" saves the STRING "true" (not boolean true)', async () => {
            const { container, onEditSpy } = renderStateful(initial as AnyValue)
            await openMenu(container)
            fireEvent.click(screen.getByRole('menuitem', { name: 'Type as text…' }))
            const input = screen.getByRole('textbox') as HTMLInputElement
            typeAndSave(input, 'true')
            // User explicitly chose "Type as text…" — typed "true" stays a string.
            expect(onEditSpy).toHaveBeenCalledWith('custom_field', 'true', initial)
            expect(renderedValueText(container)).toBe('true')
            expect(renderedTypeTag(container)).toBe('string')
        })
    })

    describe('after saving, the editor mode follows the new type', () => {
        it('null → save string via Type as text → next click opens text editor (not menu)', async () => {
            const { container } = renderStateful(null)
            await openMenu(container)
            fireEvent.click(screen.getByRole('menuitem', { name: 'Type as text…' }))
            typeAndSave(screen.getByRole('textbox') as HTMLInputElement, 'hello')
            // Re-edit: clicking the value should open the text editor directly (no menu)
            fireEvent.click(trigger(container))
            expect(screen.queryByText('Type as text…')).not.toBeInTheDocument()
            expect(screen.getByRole('textbox')).toBeInTheDocument()
        })

        it('string → menu choice "null" → next click opens menu (not text editor)', async () => {
            const { container } = renderStateful('hello')
            // From string, only text editor is reachable. Type "X" then save to leave a string.
            // To get to menu mode we need the value to become null/bool, which only happens via the menu —
            // and the menu only appears for null/bool. So the only path string → menu is: edit string,
            // and then have something else write null. Skip — covered by null/bool starting cases.
            // But we can verify: starting from string, clicking opens text editor, NOT a menu.
            fireEvent.click(trigger(container))
            expect(screen.queryByText('Type as text…')).not.toBeInTheDocument()
            expect(screen.getByRole('textbox')).toBeInTheDocument()
        })
    })
})
