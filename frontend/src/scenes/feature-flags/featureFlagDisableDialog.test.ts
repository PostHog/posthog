import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { FeatureFlagDisableDialogOption, openFeatureFlagDisableDialog } from './featureFlagDisableDialog'

jest.mock('posthog-js')

const EXPERIMENT_KEY = FEATURE_FLAGS.FEATURE_FLAG_DISABLE_AND_ARCHIVE_EXPERIMENT

describe('openFeatureFlagDisableDialog', () => {
    let flagsLogic: ReturnType<typeof enabledFeaturesLogic.build>
    let onDisable: jest.Mock
    let onDisableAndArchive: jest.Mock
    let openControlDialog: jest.Mock
    let openDialog: jest.SpyInstance

    const setVariant = (variant: string | boolean): void => {
        flagsLogic.actions.setFeatureFlags([EXPERIMENT_KEY], { [EXPERIMENT_KEY]: variant })
    }

    const open = (): void =>
        openFeatureFlagDisableDialog({
            source: 'feature-flags-list',
            onDisable,
            onDisableAndArchive,
            openControlDialog,
        })

    const optionCapturesOf = (option: FeatureFlagDisableDialogOption): any[][] =>
        (posthog.capture as jest.Mock).mock.calls.filter(
            ([name, props]) => name === 'feature flag disable confirmation option selected' && props?.option === option
        )

    beforeEach(() => {
        initKeaTests()
        flagsLogic = enabledFeaturesLogic()
        flagsLogic.mount()
        onDisable = jest.fn()
        onDisableAndArchive = jest.fn()
        openControlDialog = jest.fn()
        openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        flagsLogic.unmount()
        jest.restoreAllMocks()
    })

    describe('variant routing', () => {
        it('offers "Disable and archive" to the test variant', () => {
            setVariant('test')
            open()

            expect(openControlDialog).not.toHaveBeenCalled()
            expect(openDialog.mock.calls[0][0].primaryButton.children).toBe('Disable and archive')
            expect(openDialog.mock.calls[0][0].secondaryButton.children).toBe('Disable only')
        })

        it.each<[string, string | boolean]>([
            ['control', 'control'],
            ['an unset flag', false],
            ['an unexpected variant', 'holdout'],
        ])("falls back to the caller's own dialog for %s", (_label, variant) => {
            setVariant(variant)
            open()

            expect(openDialog).not.toHaveBeenCalled()
            expect(openControlDialog).toHaveBeenCalledTimes(1)
        })
    })

    describe('option telemetry', () => {
        // A fresh dialog per case, so each one can assert the other callback stayed untouched.
        it.each<[FeatureFlagDisableDialogOption, 'primaryButton' | 'secondaryButton' | 'tertiaryButton']>([
            ['disable_and_archive', 'primaryButton'],
            ['disable', 'secondaryButton'],
            ['cancel', 'tertiaryButton'],
        ])('reports %s and runs only its own callback', (option, button) => {
            setVariant('test')
            open()

            openDialog.mock.calls[0][0][button].onClick()

            expect(optionCapturesOf(option)).toEqual([
                ['feature flag disable confirmation option selected', { source: 'feature-flags-list', option }],
            ])
            expect(onDisableAndArchive).toHaveBeenCalledTimes(option === 'disable_and_archive' ? 1 : 0)
            expect(onDisable).toHaveBeenCalledTimes(option === 'disable' ? 1 : 0)
        })

        it('wraps the control dialog callbacks so control reports the same options', () => {
            setVariant('control')
            open()
            const [confirm, cancel] = openControlDialog.mock.calls[0]

            confirm()
            expect(optionCapturesOf('disable')).toHaveLength(1)
            expect(onDisable).toHaveBeenCalledTimes(1)

            cancel()
            expect(optionCapturesOf('cancel')).toHaveLength(1)
            expect(onDisableAndArchive).not.toHaveBeenCalled()
        })
    })
})
