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
    fireEvent.click(screen.getByRole('menuitem', { name: label }))
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
})
