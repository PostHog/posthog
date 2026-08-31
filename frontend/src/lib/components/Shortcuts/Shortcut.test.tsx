import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

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
})
