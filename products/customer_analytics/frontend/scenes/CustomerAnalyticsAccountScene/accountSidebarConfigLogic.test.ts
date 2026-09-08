import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    UserCustomerAnalyticsConfigApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    accountSidebarConfigLogic,
    configuratorKeysToPinnedProperties,
    pinnedPropertyToConfiguratorKey,
} from './accountSidebarConfigLogic'
import { MAX_PINNED_ACCOUNT_PROPERTIES } from './components/accountPropertyTypes'

const CONFIG_URL = '/api/projects/:team_id/user_customer_analytics_config/@me/'
const CUSTOM_PROPERTIES_URL = '/api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIPS_URL = '/api/projects/:team_id/account_relationship_definitions/'

const buildCustomProperty = (overrides: Partial<CustomPropertyDefinitionApi> = {}): CustomPropertyDefinitionApi =>
    ({
        id: 'custom-1',
        name: 'ARR',
        description: null,
        display_type: 'currency',
        target_type: 'account',
        is_big_number: false,
        is_canonical: false,
        options: null,
        source: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: '2026-01-01T00:00:00Z',
        references: [],
        has_workflow_reference: false,
        ...overrides,
    }) as CustomPropertyDefinitionApi

const buildRelationship = (
    overrides: Partial<AccountRelationshipDefinitionApi> = {}
): AccountRelationshipDefinitionApi => ({
    id: 'relationship-1',
    name: 'CSM',
    description: null,
    is_single_holder: true,
    ...overrides,
})

const defaultMocks = (
    config: UserCustomerAnalyticsConfigApi = { pinned_properties: [] }
): Parameters<typeof useMocks>[0] => ({
    get: {
        [CONFIG_URL]: config,
        [CUSTOM_PROPERTIES_URL]: { count: 1, results: [buildCustomProperty()] },
        [RELATIONSHIPS_URL]: { count: 1, results: [buildRelationship()] },
    },
    patch: {
        [CONFIG_URL]: async ({ request }) => await request.json(),
    },
})

describe('accountSidebarConfigLogic', () => {
    let logic: ReturnType<typeof accountSidebarConfigLogic.build>

    const mountLogic = async (): Promise<void> => {
        logic = accountSidebarConfigLogic({ projectId: 1 })
        logic.mount()
        await expectLogic(logic)
            .toDispatchActionsInAnyOrder(['loadConfigSuccess', 'loadAvailableDefinitionsSuccess'])
            .toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('keys state by project and converts heterogeneous configurator keys', () => {
        const firstProjectLogic = accountSidebarConfigLogic({ projectId: 1 })
        const secondProjectLogic = accountSidebarConfigLogic({ projectId: 2 })

        expect(firstProjectLogic.key).not.toEqual(secondProjectLogic.key)
        expect(pinnedPropertyToConfiguratorKey({ kind: 'custom_property', id: 'shared-id' })).toBe('custom:shared-id')
        expect(pinnedPropertyToConfiguratorKey({ kind: 'relationship', id: 'shared-id' })).toBe(
            'relationship:shared-id'
        )
        expect(
            configuratorKeysToPinnedProperties([
                'relationship:relationship-1',
                'custom:custom-1',
                'unknown:ignored',
                'custom:',
            ])
        ).toEqual([
            { kind: 'relationship', id: 'relationship-1' },
            { kind: 'custom_property', id: 'custom-1' },
        ])
    })

    it('loads every definition page and keeps account custom properties only', async () => {
        const customOffsets: number[] = []
        const relationshipOffsets: number[] = []
        useMocks({
            get: {
                [CONFIG_URL]: { pinned_properties: [] },
                [CUSTOM_PROPERTIES_URL]: ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset'))
                    customOffsets.push(offset)
                    return offset === 0
                        ? {
                              count: 101,
                              results: Array.from({ length: 100 }, (_, index) =>
                                  buildCustomProperty({ id: `custom-${index}` })
                              ),
                          }
                        : {
                              count: 101,
                              results: [buildCustomProperty({ id: 'person-1', target_type: 'person' })],
                          }
                },
                [RELATIONSHIPS_URL]: ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset'))
                    relationshipOffsets.push(offset)
                    return offset === 0
                        ? {
                              count: 101,
                              results: Array.from({ length: 100 }, (_, index) =>
                                  buildRelationship({ id: `relationship-${index}` })
                              ),
                          }
                        : { count: 101, results: [buildRelationship({ id: 'relationship-last' })] }
                },
            },
        })

        await mountLogic()

        expect(customOffsets).toEqual([0, 100])
        expect(relationshipOffsets).toEqual([0, 100])
        expect(logic.values.availableDefinitions?.customProperties).toHaveLength(100)
        expect(logic.values.availableDefinitions?.relationships).toHaveLength(101)
    })

    it('exposes configuration load failures for an inline retry state', async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                [CONFIG_URL]: () => [500, { detail: 'Could not load configuration.' }],
                [CUSTOM_PROPERTIES_URL]: { count: 0, results: [] },
                [RELATIONSHIPS_URL]: { count: 0, results: [] },
            },
        })
        logic = accountSidebarConfigLogic({ projectId: 1 })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActionsInAnyOrder(['loadConfigFailure', 'loadAvailableDefinitionsSuccess'])
            .toFinishAllListeners()

        expect(logic.values.configLoadFailed).toBe(true)
        expect(logic.values.availableDefinitionsLoadFailed).toBe(false)
    })

    it('resolves pins in stored order and exposes stale references', async () => {
        useMocks(
            defaultMocks({
                pinned_properties: [
                    { kind: 'custom_property', id: 'custom-1' },
                    { kind: 'relationship', id: 'relationship-1' },
                    { kind: 'custom_property', id: 'missing' },
                ],
            })
        )

        await mountLogic()

        expect(logic.values.resolvedPinnedProperties.map(({ reference }) => reference.id)).toEqual([
            'custom-1',
            'relationship-1',
        ])
        expect(logic.values.stalePinnedProperties).toEqual([{ kind: 'custom_property', id: 'missing' }])
    })

    it('supports configure, toggle, reorder, cancel, and the 50-property limit', async () => {
        useMocks(defaultMocks({ pinned_properties: [{ kind: 'custom_property', id: 'custom-1' }] }))
        await mountLogic()

        logic.actions.beginConfiguring()
        logic.actions.togglePinnedProperty({ kind: 'relationship', id: 'relationship-1' })
        logic.actions.movePinnedProperty(1, 0)
        expect(logic.values.draftPinnedProperties.map(({ id }) => id)).toEqual(['relationship-1', 'custom-1'])

        logic.actions.cancelConfiguring()
        expect(logic.values.isConfiguring).toBe(false)
        expect(logic.values.draftPinnedProperties).toEqual([{ kind: 'custom_property', id: 'custom-1' }])

        const fullDraft = Array.from({ length: MAX_PINNED_ACCOUNT_PROPERTIES }, (_, index) => ({
            kind: 'custom_property' as const,
            id: `custom-${index}`,
        }))
        logic.actions.setDraftPinnedProperties(fullDraft)
        logic.actions.togglePinnedProperty({ kind: 'custom_property', id: 'overflow' })
        expect(logic.values.draftPinnedProperties).toEqual(fullDraft)
        expect(logic.values.draftPinLimitReached).toBe(true)
    })

    it('saves once while a request is active and adopts the server response', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        let releasePatch: (() => void) | undefined
        let patchCount = 0
        let submittedBody: unknown
        useMocks({
            ...defaultMocks({ pinned_properties: [{ kind: 'custom_property', id: 'custom-1' }] }),
            patch: {
                [CONFIG_URL]: async ({ request }) => {
                    patchCount += 1
                    submittedBody = await request.json()
                    await new Promise<void>((resolve) => {
                        releasePatch = resolve
                    })
                    return submittedBody
                },
            },
        })
        await mountLogic()
        logic.actions.beginConfiguring()
        logic.actions.togglePinnedProperty({ kind: 'relationship', id: 'relationship-1' })

        await expectLogic(logic, () => logic.actions.savePinnedProperties()).toDispatchActions([
            'persistPinnedProperties',
        ])
        await waitFor(() => expect(patchCount).toBe(1))
        await expectLogic(logic, () => logic.actions.savePinnedProperties()).toNotHaveDispatchedActions([
            'persistPinnedProperties',
        ])
        releasePatch?.()
        await expectLogic(logic).toDispatchActions(['persistPinnedPropertiesSuccess']).toFinishAllListeners()

        expect(patchCount).toBe(1)
        expect(submittedBody).toEqual({
            pinned_properties: [
                { kind: 'custom_property', id: 'custom-1' },
                { kind: 'relationship', id: 'relationship-1' },
            ],
        })
        expect(logic.values.config?.pinned_properties).toEqual(
            (submittedBody as UserCustomerAnalyticsConfigApi).pinned_properties
        )
        expect(logic.values.isConfiguring).toBe(false)
        expect(captureSpy).toHaveBeenCalledWith(AccountsEvents.PinnedPropertiesSaved, {
            pinned_count: 2,
            custom_property_count: 1,
            relationship_count: 1,
        })
    })

    it('keeps the draft open for retry and shows one notification when saving fails', async () => {
        silenceKeaLoadersErrors()
        const toastSpy = jest.spyOn(lemonToast, 'error')
        const captureSpy = jest.spyOn(posthog, 'capture')
        useMocks({
            ...defaultMocks({ pinned_properties: [{ kind: 'custom_property', id: 'custom-1' }] }),
            patch: { [CONFIG_URL]: () => [500, { detail: 'Could not save pinned properties.' }] },
        })
        await mountLogic()
        logic.actions.beginConfiguring()
        logic.actions.togglePinnedProperty({ kind: 'relationship', id: 'relationship-1' })
        logic.actions.movePinnedProperty(1, 0)

        await expectLogic(logic, () => logic.actions.savePinnedProperties())
            .toDispatchActions(['persistPinnedPropertiesFailure'])
            .toFinishAllListeners()

        expect(logic.values.config?.pinned_properties).toEqual([{ kind: 'custom_property', id: 'custom-1' }])
        expect(logic.values.draftPinnedProperties).toEqual([
            { kind: 'relationship', id: 'relationship-1' },
            { kind: 'custom_property', id: 'custom-1' },
        ])
        expect(logic.values.isConfiguring).toBe(true)
        expect(logic.values.canSavePinnedProperties).toBe(true)
        expect(toastSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy).not.toHaveBeenCalledWith(AccountsEvents.PinnedPropertiesSaved, expect.anything())
    })
})
