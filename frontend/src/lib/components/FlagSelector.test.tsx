import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { FlagSelector, flagSelectorButtonLabel } from './FlagSelector'

describe('FlagSelector trigger id', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // A field label associates with the picker by pointing its `htmlFor` at the trigger button's id.
    // If FlagSelector stops putting that id on the button, clicking the label reaches nothing — the
    // create-form dead click this fix removes. Guard that the id lands on the focusable button.
    it('forwards id to the trigger button', () => {
        render(
            <Provider>
                <FlagSelector id="flag-selector-under-test" value={undefined} onChange={() => {}} />
            </Provider>
        )

        expect(screen.getByText('Select flag').closest('button')).toHaveAttribute('id', 'flag-selector-under-test')
    })
})

describe('flagSelectorButtonLabel', () => {
    // The picker strips `key` off recently-used flags, so a pick from the Recent tab labels itself
    // with `name`, which on a flag holds a description like "Feature Flag for Early Access Feature
    // Foo". The resolved key has to win over that.
    const RECENT_PICK = { id: 7, label: 'Feature Flag for Early Access Feature Foo' }

    test.each([
        ['resolved key wins over a recent pick', 'foo', 7, RECENT_PICK, 'Fallback', 'foo'],
        ['pick stands in while the key is still loading', '', 7, RECENT_PICK, 'Fallback', RECENT_PICK.label],
        ['pick stands in when the key lookup fails', '', 7, { id: 7, label: 'foo' }, 'Fallback', 'foo'],
        ['pick the caller never stored is dropped', '', undefined, RECENT_PICK, 'Fallback', 'Fallback'],
        ['pick for a different flag is dropped', '', 9, RECENT_PICK, 'Fallback', 'Fallback'],
        ['falls back to the initial label with nothing picked', '', undefined, undefined, 'Fallback', 'Fallback'],
        ['falls back to the default with no initial label', '', undefined, undefined, undefined, 'Select flag'],
    ])(
        '%s',
        (
            _name: string,
            flagKey: string,
            value: number | undefined,
            pickedFlag: { id: number; label: string } | undefined,
            initialButtonLabel: string | undefined,
            expected: string
        ) => {
            expect(flagSelectorButtonLabel({ flagKey, value, pickedFlag, initialButtonLabel })).toBe(expected)
        }
    )
})
