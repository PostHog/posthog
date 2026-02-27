import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'

import { PipelineResultType, isOkResult } from '../pipelines/results'
import { createGroupTypeMappingStep } from './group-type-mapping-step'

describe('createGroupTypeMappingStep', () => {
    let mockGroupTypeManager: jest.Mocked<GroupTypeManager>
    let step: ReturnType<typeof createGroupTypeMappingStep>

    const team = createTestTeam({ id: 123 })

    beforeEach(() => {
        mockGroupTypeManager = {
            fetchGroupTypes: jest.fn(),
            fetchGroupTypeIndex: jest.fn(),
            insertGroupType: jest.fn(),
        } as unknown as jest.Mocked<GroupTypeManager>
        step = createGroupTypeMappingStep(mockGroupTypeManager)
    })

    it('maps group types to indexes when groups are present', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: {
                    company: 'acme-corp',
                    project: 'project-123',
                },
                existing: 'property',
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex
            .mockResolvedValueOnce(0) // company -> 0
            .mockResolvedValueOnce(1) // project -> 1

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({
                $groups: {
                    company: 'acme-corp',
                    project: 'project-123',
                },
                existing: 'property',
                $group_0: 'acme-corp',
                $group_1: 'project-123',
            })
        }
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledTimes(2)
    })

    it('passes through event unchanged when no $groups property', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { existing: 'property' },
        })

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ existing: 'property' })
        }
        expect(mockGroupTypeManager.fetchGroupTypes).not.toHaveBeenCalled()
    })

    it('passes through event unchanged when $groups is empty', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { $groups: {}, existing: 'property' },
        })

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ $groups: {}, existing: 'property' })
        }
        expect(mockGroupTypeManager.fetchGroupTypes).not.toHaveBeenCalled()
    })

    it('skips group types not in the mapping', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: {
                    company: 'acme-corp',
                    unknown_group: 'value',
                },
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex
            .mockResolvedValueOnce(0) // company -> 0
            .mockResolvedValueOnce(null) // unknown_group -> null (not found)

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties?.$group_0).toBe('acme-corp')
            expect(result.value.event.properties?.$group_1).toBeUndefined()
        }
    })

    it('handles multiple group types with non-sequential indexes', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: {
                    company: 'acme-corp',
                    department: 'engineering',
                },
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex
            .mockResolvedValueOnce(0) // company -> 0
            .mockResolvedValueOnce(3) // department -> 3 (non-sequential)

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties?.$group_0).toBe('acme-corp')
            expect(result.value.event.properties?.$group_3).toBe('engineering')
        }
    })

    it('handles empty group type mapping', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: {
                    company: 'acme-corp',
                },
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex.mockResolvedValueOnce(null) // No mapping found

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        // No $group_* properties should be added
        if (isOkResult(result)) {
            expect(result.value.event.properties?.$group_0).toBeUndefined()
        }
    })

    it('preserves original input structure', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: { company: 'acme-corp' },
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex.mockResolvedValueOnce(0) // company -> 0

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.team).toBe(team)
        }
    })

    it('handles $groups with null/undefined values', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: {
                $groups: {
                    company: 'acme-corp',
                    project: null as any,
                },
            },
        })

        mockGroupTypeManager.fetchGroupTypeIndex
            .mockResolvedValueOnce(0) // company -> 0
            .mockResolvedValueOnce(1) // project -> 1

        const result = await step({ event, team })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties?.$group_0).toBe('acme-corp')
            expect(result.value.event.properties?.$group_1).toBeNull()
        }
    })
})
