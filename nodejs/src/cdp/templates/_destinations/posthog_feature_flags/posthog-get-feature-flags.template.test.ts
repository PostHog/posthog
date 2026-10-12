import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-get-feature-flags.template'

describe('posthog get feature flags template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        // An environment of project 2: flags live on the project's root team.
        tester.mockTeamManager.getTeam.mockResolvedValue({ id: 5, project_id: 2 })
        tester.mockFeatureFlagRepository.list
            .mockReset()
            .mockResolvedValue({ count: 1, keys: ['beta'], flags: [{ key: 'beta' }], has_more: false })
    })

    it('lists the root team flags with the configured filters and returns them', async () => {
        const before = DateTime.utc().minus({ days: 7 }).toMillis()

        let response = await tester.invoke({
            status: 'any',
            search: '',
            targeting_property: 'project_id',
            targeting_value: '2',
            targeting_match: 'only',
            created_more_than_days_ago: 7,
            updated_more_than_days_ago: null,
            limit: 500,
        })
        response = await tester.resumeInvocation(response.invocation)

        const after = DateTime.utc().minus({ days: 7 }).toMillis()
        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual({ count: 1, keys: ['beta'], flags: [{ key: 'beta' }], has_more: false })
        expect(tester.mockFeatureFlagRepository.list).toHaveBeenCalledWith(2, {
            status: 'any',
            search: null,
            createdBefore: expect.any(Date),
            updatedBefore: null,
            targeting: { property: 'project_id', value: '2', match: 'only' },
            limit: 100,
        })
        const createdBefore = tester.mockFeatureFlagRepository.list.mock.calls[0][1].createdBefore.getTime()
        expect(createdBefore).toBeGreaterThanOrEqual(before)
        expect(createdBefore).toBeLessThanOrEqual(after)
    })

    it('cuts the flag list to fit the workflow variable size limit', async () => {
        const flags = Array.from({ length: 25 }, (_, index) => ({
            id: index,
            key: `flag-with-a-fairly-long-descriptive-key-${index}`,
            name: 'A long human readable description of what this feature flag controls in the product',
            active: true,
            created_at: '2026-01-01T00:00:00.000Z',
            updated_at: '2026-01-02T00:00:00.000Z',
            created_by_email: 'someone.with.a.long.name@example.com',
        }))
        tester.mockFeatureFlagRepository.list.mockResolvedValue({
            count: flags.length,
            keys: flags.map((flag) => flag.key),
            flags,
            has_more: false,
        })

        let response = await tester.invoke({ status: 'enabled' })
        response = await tester.resumeInvocation(response.invocation)

        const result = response.execResult as {
            count: number
            keys: string[]
            flags: { key: string }[]
            has_more: boolean
        }
        expect(response.error).toBeUndefined()
        expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(4096)
        expect(result.flags.length).toBeGreaterThan(0)
        expect(result).toMatchObject({ count: result.flags.length, has_more: true })
        expect(result.keys).toEqual(result.flags.map((flag) => flag.key))
    })

    it('fails when only one of the release condition fields is set', async () => {
        const response = await tester.invoke({
            status: 'enabled',
            targeting_property: 'project_id',
            targeting_value: '',
        })

        expect(response.error).toContain("needs both 'targeting_property' and 'targeting_value'")
        expect(tester.mockFeatureFlagRepository.list).not.toHaveBeenCalled()
    })
})
