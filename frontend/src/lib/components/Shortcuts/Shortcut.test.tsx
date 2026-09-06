import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { Shortcut } from './Shortcut'
import { keyBinds } from './shortcuts'

describe('Shortcut', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    // A wrapper such as AccessControlAction guards the child by injecting disabledReason through Shortcut.
    // Shortcut must forward that guard to the child, otherwise a viewer sees an enabled create button that
    // fails with a silent 403 on click.
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

    // The guard must also survive a wrapper between Shortcut and the button. On the saved insights
    // scene the Shortcut child is a LemonDropdown, so the guard reaches the dropdown, not the visible
    // trigger. Without forwarding, a viewer could still open the create menu.
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

        // The guarded trigger blocks its click, so the portal never mounts; an unguarded one opens it.
        const menuOpened = screen.queryByText('Create menu item') !== null
        expect(menuOpened).toBe(canOpen)
    })
})
