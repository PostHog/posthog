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
            .mockResolvedValue({ count: 1, keys: ['beta'], flags: [{ key: 'beta' }] })
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
        expect(response.execResult).toEqual({ count: 1, keys: ['beta'], flags: [{ key: 'beta' }] })
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
