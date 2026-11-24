import { cleanup, render } from '@testing-library/react'

import { Button, Checkbox, Switch } from '@posthog/quill'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { UiSound, uiSoundForTarget } from './uiSoundForTarget'

describe('uiSoundForTarget', () => {
    afterEach(() => {
        cleanup()
    })

    it.each<{ name: string; element: JSX.Element; pressed: string; expected: UiSound | null }>([
        {
            name: 'LemonButton',
            element: <LemonButton>Save</LemonButton>,
            pressed: '.LemonButton__content',
            expected: 'click',
        },
        {
            name: 'disabled LemonButton',
            element: <LemonButton disabledReason="Not allowed">Save</LemonButton>,
            pressed: '.LemonButton__content',
            expected: null,
        },
        {
            name: 'LemonTabs tab',
            element: (
                <LemonTabs
                    activeKey="a"
                    onChange={() => {}}
                    tabs={[
                        { key: 'a', label: 'First' },
                        { key: 'b', label: 'Second' },
                    ]}
                />
            ),
            pressed: '[role="tab"]:not([aria-selected="true"])',
            expected: 'click',
        },
        {
            name: 'LemonSwitch that is off',
            element: <LemonSwitch checked={false} onChange={() => {}} />,
            pressed: '[role="switch"]',
            expected: 'toggle-on',
        },
        {
            name: 'LemonSwitch that is on',
            element: <LemonSwitch checked onChange={() => {}} />,
            pressed: '[role="switch"]',
            expected: 'toggle-off',
        },
        {
            name: 'LemonCheckbox that is on',
            element: <LemonCheckbox checked onChange={() => {}} label="Include" />,
            pressed: 'label',
            expected: 'toggle-off',
        },
        { name: 'quill Button', element: <Button>Save</Button>, pressed: 'button', expected: 'click' },
        { name: 'disabled quill Button', element: <Button disabled>Save</Button>, pressed: 'button', expected: null },
        {
            name: 'quill Switch that is on',
            element: <Switch checked />,
            pressed: '[role="switch"]',
            expected: 'toggle-off',
        },
        {
            name: 'quill Checkbox that is off',
            element: <Checkbox />,
            pressed: '[role="checkbox"]',
            expected: 'toggle-on',
        },
        {
            name: 'label beside a quill Switch that is on',
            element: (
                <>
                    <label htmlFor="sounds-switch">Play button sounds</label>
                    <Switch id="sounds-switch" checked />
                </>
            ),
            pressed: 'label',
            expected: 'toggle-off',
        },
        { name: 'plain button', element: <button type="button">Save</button>, pressed: 'button', expected: null },
    ])('a press on $name plays $expected', ({ element, pressed, expected }) => {
        const { container } = render(element)

        const target = container.querySelector(pressed)

        expect(target).not.toBeNull()
        expect(uiSoundForTarget(target)).toEqual(expected)
    })
})
