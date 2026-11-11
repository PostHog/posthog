import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { Shortcut } from './Shortcut'
import { keyBinds } from './shortcuts'
import { useShortcut } from './useShortcut'

function TestSidebarShortcut({ onToggle }: { onToggle: () => void }): JSX.Element {
    useShortcut({
        name: 'TestSidebarShortcut',
        keybind: [keyBinds.toggleLeftNav, keyBinds.toggleLeftNavFallback],
        intent: 'Toggle sidebar',
        interaction: 'function',
        callback: onToggle,
        ignoreInEditable: true,
    })

    return (
        <>
            <input aria-label="Shortcut input" />
            <div role="textbox" aria-label="Rich text editor" contentEditable />
        </>
    )
}

describe('Shortcut', () => {
    // RTL auto-cleanup is not enabled in this repo, so `screen` leaks between tests without this.
    afterEach(() => {
        cleanup()
    })

    test.each([
        { key: 'b', ctrlKey: true, target: 'body', toggles: true },
        { key: '[', ctrlKey: false, target: 'body', toggles: true },
        { key: 'b', ctrlKey: true, target: 'input', toggles: false },
        { key: 'b', ctrlKey: true, target: 'editor', toggles: false },
    ])('sidebar shortcut with $key on $target toggles=$toggles', ({ key, ctrlKey, target, toggles }) => {
        const onToggle = jest.fn()
        render(<TestSidebarShortcut onToggle={onToggle} />)

        const element =
            target === 'input'
                ? screen.getByLabelText('Shortcut input')
                : target === 'editor'
                  ? screen.getByLabelText('Rich text editor')
                  : document.body
        if (target === 'editor') {
            Object.defineProperty(element, 'isContentEditable', { value: true })
        }
        const event = new KeyboardEvent('keydown', { key, ctrlKey, bubbles: true, cancelable: true })
        fireEvent(element, event)

        expect(onToggle).toHaveBeenCalledTimes(toggles ? 1 : 0)
        expect(event.defaultPrevented).toBe(toggles)
    })

    test.each([
        { target: 'input', clicks: 0 },
        { target: 'body', clicks: 1 },
    ])('Shortcut with ignoreInEditable on $target clicks=$clicks', ({ target, clicks }) => {
        const onClick = jest.fn()
        render(
            <>
                <input aria-label="Shortcut input" />
                <Shortcut
                    name="TestIgnoreInEditable"
                    keybind={[['x']]}
                    intent="Test editable target suppression"
                    interaction="click"
                    ignoreInEditable
                >
                    <LemonButton onClick={onClick}>Shortcut target</LemonButton>
                </Shortcut>
            </>
        )

        fireEvent.keyDown(target === 'input' ? screen.getByLabelText('Shortcut input') : document.body, { key: 'x' })

        expect(onClick).toHaveBeenCalledTimes(clicks)
    })

    test.each([
        { capture: 'ctrl', key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, triggered: false },
        { capture: 'ctrl', key: 'j', ctrlKey: true, metaKey: false, shiftKey: false, triggered: false },
        { capture: undefined, key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, triggered: true },
        { capture: 'ctrl', key: 'k', ctrlKey: false, metaKey: true, shiftKey: false, triggered: true },
        { capture: 'ctrl', key: '`', ctrlKey: true, metaKey: false, shiftKey: false, triggered: true },
        { capture: 'ctrl', key: '~', ctrlKey: true, metaKey: false, shiftKey: true, triggered: true },
        { capture: 'all', key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, triggered: false },
        { capture: 'all', key: 'Escape', ctrlKey: false, metaKey: false, shiftKey: false, triggered: false },
        { capture: undefined, key: 'Escape', ctrlKey: false, metaKey: false, shiftKey: false, triggered: true },
    ])('respects keyboard capture: %j', ({ capture, key, ctrlKey, metaKey, shiftKey, triggered }) => {
        const onClick = jest.fn()
        render(
            <div data-shortcuts-ignore={capture} data-shortcuts-allow-keys="` ~">
                <div tabIndex={0} role="application" aria-label="Terminal" />
                <Shortcut
                    name="TestControlCapture"
                    keybind={[
                        [...(ctrlKey || metaKey ? ['command'] : []), ...(shiftKey ? ['shift'] : []), key.toLowerCase()],
                    ]}
                    intent="Test shortcut"
                    interaction="click"
                >
                    <LemonButton onClick={onClick}>Test shortcut</LemonButton>
                </Shortcut>
            </div>
        )

        fireEvent.keyDown(screen.getByLabelText('Terminal'), { key, ctrlKey, metaKey, shiftKey })

        expect(onClick).toHaveBeenCalledTimes(triggered ? 1 : 0)
    })

    test('captured input interrupts a pending shortcut sequence', () => {
        const onClick = jest.fn()
        render(
            <>
                <div data-shortcuts-ignore="all" tabIndex={0} aria-label="Game" />
                <Shortcut name="TestSequence" keybind={[['g', 'then', 'p']]} intent="Test sequence" interaction="click">
                    <LemonButton onClick={onClick}>Sequence shortcut</LemonButton>
                </Shortcut>
            </>
        )

        fireEvent.keyDown(document.body, { key: 'g' })
        fireEvent.keyDown(screen.getByLabelText('Game'), { key: 'ArrowUp' })
        fireEvent.keyDown(document.body, { key: 'p' })
        expect(onClick).not.toHaveBeenCalled()

        fireEvent.keyDown(document.body, { key: 'g' })
        fireEvent.keyDown(document.body, { key: 'p' })
        expect(onClick).toHaveBeenCalledTimes(1)
    })

    // AccessControlAction injects disabledReason through Shortcut, which must forward it to the child.
    test.each([
        [AccessControlLevel.Viewer, false],
        [AccessControlLevel.Editor, true],
    ])('with %s access the button is clickable=%s', async (userAccessLevel, clickable) => {
        const onClick = jest.fn()

        render(
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={userAccessLevel}
            >
                <Shortcut name="TestNew" keybind={[keyBinds.new]} intent="New" interaction="click">
                    <LemonButton type="primary" onClick={onClick}>
                        New
                    </LemonButton>
                </Shortcut>
            </AccessControlAction>
        )

        await userEvent.click(screen.getByText('New'))

        expect(onClick).toHaveBeenCalledTimes(clickable ? 1 : 0)
    })

    // On the saved insights scene the child is a LemonDropdown, so the guard lands on the dropdown
    // rather than on the visible trigger.
    test.each([
        [AccessControlLevel.Viewer, false],
        [AccessControlLevel.Editor, true],
    ])('with %s access a wrapped dropdown opens its menu=%s', async (userAccessLevel, canOpen) => {
        render(
            <AccessControlAction
                resourceType={AccessControlResourceType.Insight}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={userAccessLevel}
            >
                <Shortcut name="TestNewInsight" keybind={[keyBinds.new]} intent="New" interaction="click">
                    <LemonDropdown overlay={<span>Create menu item</span>} placement="bottom-end">
                        <LemonButton type="primary">New</LemonButton>
                    </LemonDropdown>
                </Shortcut>
            </AccessControlAction>
        )

        await userEvent.click(screen.getByText('New'))

        const menuOpened = screen.queryByText('Create menu item') !== null
        expect(menuOpened).toBe(canOpen)
    })
})
