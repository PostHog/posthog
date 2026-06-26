import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { shareNudgeLogic } from './shareNudgeLogic'

jest.mock('posthog-js')

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_SHARE_NUDGE_V2

function setVariant(variant: string): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FLAG]: variant })
}

function setMemberCount(memberCount: number): void {
    organizationLogic.actions.loadCurrentOrganizationSuccess({
        ...MOCK_DEFAULT_ORGANIZATION,
        member_count: memberCount,
    })
}

function capturesOf(event: string): any[][] {
    return (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)
}

describe('shareNudgeLogic', () => {
    let logic: ReturnType<typeof shareNudgeLogic.build>
    let randomSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        randomSpy = jest.spyOn(Math, 'random').mockReturnValue(0)
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
        jest.restoreAllMocks()
    })

    function mount(variant: string): void {
        setVariant(variant)
        logic = shareNudgeLogic()
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    }

    it('shows the export prompt when variant is "export" and the probability gate passes', () => {
        randomSpy.mockReturnValue(0.1)
        mount('export')

        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(true)
        expect(logic.values.promptSource).toBe('export_prompt')
        expect(capturesOf('web analytics share nudge prompt shown')).toEqual([
            ['web analytics share nudge prompt shown', { source: 'export_prompt' }],
        ])
    })

    it('does not show the prompt when the probability gate fails', () => {
        randomSpy.mockReturnValue(0.9)
        mount('export')

        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(false)
        expect(capturesOf('web analytics share nudge prompt shown')).toHaveLength(0)
    })

    it.each([['banner'], ['control'], ['control_b']])('does not show the prompt for the "%s" variant', (variant) => {
        randomSpy.mockReturnValue(0)
        mount(variant)

        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(false)
    })

    it('does not show the prompt for a solo org even on the "export" variant', () => {
        randomSpy.mockReturnValue(0)
        setMemberCount(1)
        mount('export')

        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(false)
    })

    it('does not show the prompt when not enrolled in the flag', () => {
        randomSpy.mockReturnValue(0)
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic = shareNudgeLogic()
        logic.mount()

        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(false)
    })

    it('does not show the prompt once dismissed for the session', () => {
        randomSpy.mockReturnValue(0)
        mount('export')

        logic.actions.dismissForSession()
        logic.actions.exportTriggered()

        expect(logic.values.promptVisible).toBe(false)
    })

    it('dismissForSession hides an open export prompt', async () => {
        randomSpy.mockReturnValue(0)
        mount('export')

        logic.actions.exportTriggered()
        expect(logic.values.promptVisible).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.dismissForSession()
        }).toMatchValues({ promptVisible: false, sessionDismissed: true })
    })

    it('captures the exposure event once for the "export" variant', () => {
        setVariant('export')
        logic = shareNudgeLogic()
        logic.mount()

        expect(capturesOf('web analytics share nudge exposed')).toEqual([
            ['web analytics share nudge exposed', { variant: 'export' }],
        ])
    })
})
