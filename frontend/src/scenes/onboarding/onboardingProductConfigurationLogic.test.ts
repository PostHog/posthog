import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { ProductConfigOption, onboardingProductConfigurationLogic } from './onboardingProductConfigurationLogic'

describe('onboardingProductConfigurationLogic', () => {
    const options: ProductConfigOption[] = [
        ...(
            [
                'autocapture_opt_out',
                'heatmaps_opt_in',
                'capture_console_log_opt_in',
                'capture_performance_opt_in',
            ] as const
        ).map(
            (teamProperty): ProductConfigOption => ({
                title: teamProperty,
                description: '',
                teamProperty,
                type: 'toggle',
                value: true,
                inverseToggle: teamProperty === 'autocapture_opt_out',
                visible: teamProperty !== 'capture_console_log_opt_in',
            })
        ),
        ...(['session_recording_opt_in', 'autocapture_web_vitals_opt_in'] as const).map(
            (teamProperty): ProductConfigOption => ({
                title: teamProperty,
                description: '',
                teamProperty,
                type: 'toggle',
                value: true,
                visible: false,
            })
        ),
        {
            title: 'Masking',
            description: '',
            teamProperty: 'session_recording_masking_config',
            type: 'select',
            value: 'normal',
            selectOptions: [],
            onChange: () => ({ session_recording_masking_config: { maskAllInputs: true } }),
            visible: true,
        },
        {
            title: 'Minimum duration',
            description: '',
            teamProperty: 'session_recording_minimum_duration_milliseconds',
            type: 'select',
            value: 1000,
            selectOptions: [],
            visible: true,
        },
    ]

    it.each([
        ['member', OrganizationMembershipLevel.Member, AccessControlLevel.Member, false],
        ['admin', OrganizationMembershipLevel.Admin, AccessControlLevel.Admin, true],
        ['owner', OrganizationMembershipLevel.Owner, AccessControlLevel.Admin, true],
        ['unknown membership', null, AccessControlLevel.Member, false],
        ['admin granted by access control', OrganizationMembershipLevel.Member, AccessControlLevel.Admin, true],
    ])('saves only permitted configuration for a project %s', async (_, membershipLevel, accessLevel, isAdmin) => {
        const team = {
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: membershipLevel,
            user_access_level: accessLevel,
        }
        initKeaTests(true, team)
        const requests: unknown[] = []
        useMocks({
            patch: {
                '/api/environments/:id': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    requests.push(body)
                    return [200, { ...team, ...body }]
                },
            },
        })
        const logic = onboardingProductConfigurationLogic()
        logic.mount()
        logic.actions.setConfigOptions(options)

        await expectLogic(logic, () => logic.actions.saveConfiguration()).toDispatchActions([
            teamLogic.actionTypes.updateCurrentTeamSuccess,
        ])

        expect(requests).toEqual([
            {
                session_recording_opt_in: true,
                autocapture_web_vitals_opt_in: true,
                ...(isAdmin
                    ? {
                          autocapture_opt_out: false,
                          heatmaps_opt_in: true,
                          capture_console_log_opt_in: true,
                          capture_performance_opt_in: true,
                          session_recording_masking_config: { maskAllInputs: true },
                          session_recording_minimum_duration_milliseconds: 1000,
                      }
                    : {}),
            },
        ])
        expect(logic.values.canConfigureTeamProperty('session_recording_opt_in')).toBe(true)
        expect(logic.values.canConfigureTeamProperty('session_recording_masking_config')).toBe(isAdmin)
    })

    it.each([false, true])(
        'filters callback output and skips empty member updates (callback: %s)',
        async (useCallback) => {
            initKeaTests(true, {
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Member,
                user_access_level: AccessControlLevel.Member,
            })
            const requests: unknown[] = []
            useMocks({
                patch: {
                    '/api/environments/:id': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        requests.push(body)
                        return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                    },
                },
            })
            const logic = onboardingProductConfigurationLogic()
            logic.mount()
            logic.actions.setConfigOptions(
                useCallback
                    ? [
                          {
                              title: 'Web vitals',
                              description: '',
                              teamProperty: 'autocapture_web_vitals_opt_in',
                              type: 'select',
                              value: 'enabled',
                              selectOptions: [],
                              onChange: () => ({
                                  autocapture_web_vitals_opt_in: true,
                                  capture_performance_opt_in: true,
                              }),
                              visible: true,
                          },
                      ]
                    : options.filter((option) => option.teamProperty === 'session_recording_masking_config')
            )

            await expectLogic(logic, () => logic.actions.saveConfiguration()).toFinishAllListeners()

            expect(requests).toEqual(useCallback ? [{ autocapture_web_vitals_opt_in: true }] : [])
        }
    )
})
