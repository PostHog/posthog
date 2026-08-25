import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'

import { FeatureFlagType } from '~/types'

import { checkFeatureFlagConfirmation } from './featureFlagConfirmationLogic'
import { DependentFlag } from './featureFlagLogic'

jest.mock('posthog-js')

describe('checkFeatureFlagConfirmation', () => {
    let onConfirm: jest.Mock
    let onDisableAndArchive: jest.Mock
    let openDialog: jest.SpyInstance

    const activeFlag = { ...NEW_FLAG, id: 1, key: 'my-flag', active: true } as FeatureFlagType
    const disabledFlag = { ...activeFlag, active: false }
    const dependent: DependentFlag = { id: 2, key: 'depends-on-my-flag' } as DependentFlag

    const disableDialogReached = (): boolean =>
        (posthog.capture as jest.Mock).mock.calls.some(
            ([name, props]) =>
                name === 'feature flag disable confirmation shown' && props?.source === 'feature-flag-detail'
        )

    // shouldDisplayConfirmation is derived the way featureFlagLogic derives it before calling in,
    // so a case that sets only dependentFlags reaches the gate the same way production does.
    const disableFlag = ({
        featureFlagConfirmationEnabled = false,
        dependentFlags = [],
    }: {
        featureFlagConfirmationEnabled?: boolean
        dependentFlags?: DependentFlag[]
    } = {}): boolean =>
        checkFeatureFlagConfirmation(
            activeFlag,
            disabledFlag,
            featureFlagConfirmationEnabled || dependentFlags.length > 0,
            undefined,
            featureFlagConfirmationEnabled,
            onConfirm,
            dependentFlags,
            true,
            true,
            onDisableAndArchive
        )

    beforeEach(() => {
        onConfirm = jest.fn()
        onDisableAndArchive = jest.fn()
        openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // The disable-and-archive shortcut must stay behind the confirmation gate: archiving a flag
    // other flags read from, or skipping a team's required confirmation, is worse than losing an
    // experiment exposure.
    it.each<[string, { featureFlagConfirmationEnabled?: boolean; dependentFlags?: DependentFlag[] }]>([
        ['other flags depend on it', { dependentFlags: [dependent] }],
        ['the team requires confirmation', { featureFlagConfirmationEnabled: true }],
    ])('does not offer disable-and-archive when %s', (_label, options) => {
        expect(disableFlag(options)).toBe(true)

        expect(disableDialogReached()).toBe(false)
        expect(onDisableAndArchive).not.toHaveBeenCalled()
        expect(openDialog).toHaveBeenCalledTimes(1)
    })

    it('routes to the disable dialog when nothing else claims the confirmation', () => {
        expect(disableFlag()).toBe(true)

        expect(disableDialogReached()).toBe(true)
    })
})
