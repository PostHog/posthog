import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { Shortcut } from './Shortcut'
import { keyBinds } from './shortcuts'

describe('Shortcut', () => {
    // RTL auto-cleanup is not enabled in this repo, so `screen` leaks between tests without this.
    afterEach(() => {
        cleanup()
    })

    test.each([
        { capture: true, key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, triggered: false },
        { capture: true, key: 'j', ctrlKey: true, metaKey: false, shiftKey: false, triggered: false },
        { capture: false, key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, triggered: true },
        { capture: true, key: 'k', ctrlKey: false, metaKey: true, shiftKey: false, triggered: true },
        { capture: true, key: '`', ctrlKey: true, metaKey: false, shiftKey: false, triggered: true },
        { capture: true, key: '~', ctrlKey: true, metaKey: false, shiftKey: true, triggered: true },
    ])('respects control-key capture: %j', ({ capture, key, ctrlKey, metaKey, shiftKey, triggered }) => {
        const onClick = jest.fn()
        render(
            <div data-shortcuts-ignore={capture ? 'ctrl' : undefined} data-shortcuts-allow-keys="` ~">
                <textarea aria-label="Terminal" />
                <Shortcut
                    name="TestControlCapture"
                    keybind={[['command', ...(shiftKey ? ['shift'] : []), key]]}
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
