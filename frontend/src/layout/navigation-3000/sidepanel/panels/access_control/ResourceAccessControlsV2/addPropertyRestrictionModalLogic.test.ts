import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { accessDetailLogic } from './accessDetailLogic'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'

describe('addPropertyRestrictionModalLogic', () => {
    let logic: ReturnType<typeof addPropertyRestrictionModalLogic.build>
    const props = { projectId: '997', scopeType: 'default' as const, subjectId: '' }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:id/access_control_default_objects': { results: [] },
                '/api/projects/:id/access_control_default_properties': { results: [] },
                '/api/projects/:id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        logic = addPropertyRestrictionModalLogic.build(props)
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('finds built-in AI properties without ingested definitions and matches canonical names', async () => {
        await expectLogic(logic, () => {
            logic.actions.openModal()
            logic.actions.setPropertyType('ai')
        }).toDispatchActions(['loadPropertyOptionsSuccess'])
        expect(logic.values.propertyOptions).toEqual(
            expect.arrayContaining([
                { id: '$ai_input', name: 'input ($ai_input)' },
                { id: '$ai_output', name: 'output ($ai_output)' },
                { id: '$ai_output_choices', name: 'output_choices ($ai_output_choices)' },
            ])
        )
        await expectLogic(logic, () => logic.actions.setSearch('$ai_output_choices')).toDispatchActions([
            'loadPropertyOptionsSuccess',
        ])
        expect(logic.values.propertyOptions).toEqual([
            { id: '$ai_output_choices', name: 'output_choices ($ai_output_choices)' },
        ])
        await expectLogic(logic, () => logic.actions.setPropertyType('event')).toDispatchActions([
            'loadPropertyOptionsSuccess',
        ])
        expect(logic.values.displayPropertyOptions).toEqual([])
    })

    it('recognizes an existing event rule when selecting its AI category entry', async () => {
        const existing = {
            property_definition_id: 'existing-input',
            property: '$ai_input',
            property_type: 'event' as const,
            access_level: AccessLevelEnumApi.None,
        }
        useMocks({
            get: { '/api/projects/:id/access_control_default_properties': { results: [existing] } },
        })
        const details = accessDetailLogic(props)
        await expectLogic(details, () => details.actions.loadProperties()).toDispatchActions(['loadPropertiesSuccess'])
        await expectLogic(logic, () => logic.actions.setPropertyType('ai')).toDispatchActions([
            'loadPropertyOptionsSuccess',
        ])
        logic.actions.setPropertyId('$ai_input')
        expect(logic.values.existingRule).toEqual(existing)
    })

    it('saves the canonical AI property once and keeps the modal open until the save succeeds', async () => {
        let releaseSave: () => void = () => {}
        const pendingSave = new Promise<void>((resolve) => {
            releaseSave = resolve
        })
        const bodies: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:id/property_access_controls/': async ({ request }) => {
                    bodies.push(await request.json())
                    await pendingSave
                    return [200, { id: 'new-rule', access_level: 'none' }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openModal()
            logic.actions.setPropertyType('ai')
        }).toDispatchActions(['loadPropertyOptionsSuccess'])
        logic.actions.setPropertyId('$ai_output_choices')
        logic.actions.setLevel(AccessLevelEnumApi.None)
        logic.actions.submitRule()
        logic.actions.submitRule()
        expect(logic.values.ruleSaving).toBe(true)
        expect(logic.values.isOpen).toBe(true)
        await expectLogic(accessDetailLogic(props), releaseSave).toDispatchActions([
            'propertyRuleSaved',
            'ruleSaveFinished',
        ])
        expect(bodies).toEqual([{ ai_property: '$ai_output_choices', access_level: 'none' }])
        expect(logic.values.isOpen).toBe(false)
        expect(logic.values.ruleSaving).toBe(false)
    })

    it('keeps the selection available for retry when saving fails', async () => {
        useMocks({ post: { '/api/projects/:id/property_access_controls/': [500, { detail: 'Try again' }] } })
        await expectLogic(logic, () => {
            logic.actions.openModal()
            logic.actions.setPropertyType('ai')
        }).toDispatchActions(['loadPropertyOptionsSuccess'])
        logic.actions.setPropertyId('$ai_input')
        await expectLogic(accessDetailLogic(props), () => logic.actions.submitRule()).toDispatchActions([
            'ruleSaveFinished',
        ])
        expect(logic.values.isOpen).toBe(true)
        expect(logic.values.propertyId).toBe('$ai_input')
        expect(logic.values.ruleSaving).toBe(false)
    })
})
