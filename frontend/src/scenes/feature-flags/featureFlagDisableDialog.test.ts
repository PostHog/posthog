import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { FeatureFlagDisableDialogOption, openFeatureFlagDisableDialog } from './featureFlagDisableDialog'

jest.mock('posthog-js')

describe('openFeatureFlagDisableDialog', () => {
    let onDisable: jest.Mock
    let onDisableAndArchive: jest.Mock
    let openDialog: jest.SpyInstance

    const open = (): void =>
        openFeatureFlagDisableDialog({
            source: 'feature-flags-list',
            onDisable,
            onDisableAndArchive,
        })

    const optionCapturesOf = (option: FeatureFlagDisableDialogOption): any[][] =>
        (posthog.capture as jest.Mock).mock.calls.filter(
            ([name, props]) => name === 'feature flag disable confirmation option selected' && props?.option === option
        )

    beforeEach(() => {
        onDisable = jest.fn()
        onDisableAndArchive = jest.fn()
        openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('makes "Disable only" the primary action and "Disable and archive" a danger secondary', () => {
        open()

        expect(openDialog.mock.calls[0][0].primaryButton.children).toBe('Disable only')
        expect(openDialog.mock.calls[0][0].secondaryButton).toMatchObject({
            children: 'Disable and archive',
            status: 'danger',
        })
    })

    // A fresh dialog per case, so each one can assert the other callback stayed untouched.
    it.each<[FeatureFlagDisableDialogOption, 'primaryButton' | 'secondaryButton' | 'tertiaryButton']>([
        ['disable', 'primaryButton'],
        ['disable_and_archive', 'secondaryButton'],
        ['cancel', 'tertiaryButton'],
    ])('reports %s and runs only its own callback', (option, button) => {
        open()

        openDialog.mock.calls[0][0][button].onClick()

        expect(optionCapturesOf(option)).toEqual([
            ['feature flag disable confirmation option selected', { source: 'feature-flags-list', option }],
        ])
        expect(onDisableAndArchive).toHaveBeenCalledTimes(option === 'disable_and_archive' ? 1 : 0)
        expect(onDisable).toHaveBeenCalledTimes(option === 'disable' ? 1 : 0)
    })
})
