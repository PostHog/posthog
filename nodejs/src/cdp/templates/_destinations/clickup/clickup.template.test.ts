import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './clickup.template'

describe('clickup template', () => {
    const tester = new TemplateTester(template)

    const commonInputs = {
        oauth: {
            access_token: 'test-access-token',
        },
        workspaceId: 'test-workspace-id',
        listId: 'test-list-id',
        taskName: 'test-name',
        description: 'test-description',
        statusId: 'to do',
        priorityId: '3',
        assigneeId: ['test-assignee-id'],
    }

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(commonInputs, {
            event: {
                properties: {
                    $lib_version: '1.0.0',
                },
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"name":"test-name","description":"test-description","assignees":["test-assignee-id"],"status":"to do","priority":"3"}",
              "headers": {
                "Authorization": "Bearer test-access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.clickup.com/api/v2/list/test-list-id/task",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { message: 'Hello, world!' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should throw an error if the request fails', async () => {
        let response = await tester.invoke(commonInputs)

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { message: 'Bad Request' },
        })

        expect(response.error).toMatchInlineSnapshot(
            `"Error from api.clickup.com (status 400): {'message': 'Bad Request'}"`
        )
        expect(response.logs.filter((l) => l.level === 'error').map((l) => l.message)).toMatchInlineSnapshot(`
            [
              "Error executing function on event event-id: Error('Error from api.clickup.com (status 400): {\\'message\\': \\'Bad Request\\'}')",
            ]
        `)
    })
})
