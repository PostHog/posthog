import api from 'lib/api'

import { GroupTypeIndex } from '~/types'

import { REMOTE_REQUESTS, RemoteContext, RemoteRequest, settleRequest } from './commandKSources'

const context: RemoteContext = {
    currentTeamId: 1,
    groupTypes: [],
    aggregationLabel: () => ({ singular: 'organization', plural: 'organizations' }),
    customerAnalyticsEnabled: false,
}

const stalled: RemoteRequest = {
    id: 'persons',
    query: 'text',
    sources: ['persons'],
    fetch: (_query, signal) =>
        new Promise((_resolve, reject) =>
            signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        ),
}

describe('settleRequest', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    test.each([
        ['settles a stalled request empty at the deadline', false, { results: { persons: [] }, failed: true }],
        ['drops a request a newer query aborted', true, null],
    ])('%s', async (_, superseded, expected) => {
        const controller = new AbortController()
        const settled = settleRequest(stalled, 'ada', controller.signal, context, 3000)

        if (superseded) {
            controller.abort()
        } else {
            jest.advanceTimersByTime(3000)
        }

        await expect(settled).resolves.toEqual(expected)
    })

    it('keeps the group types that answered when the deadline passes', async () => {
        jest.spyOn(api.groups, 'listClickhouse').mockImplementation((params, options) =>
            params.group_type_index === 0
                ? Promise.resolve({
                      columns: ['group_name'],
                      results: [[{ display_name: 'Acme', key: 'acme' }]],
                  } as any)
                : new Promise((_resolve, reject) =>
                      options?.signal?.addEventListener('abort', () => reject(options.signal?.reason))
                  )
        )
        const groups = REMOTE_REQUESTS.find((request) => request.id === 'groups')!
        const settled = settleRequest(
            groups,
            'acme',
            new AbortController().signal,
            {
                ...context,
                groupTypes: [0, 1].map((index) => ({
                    group_type: `type-${index}`,
                    group_type_index: index as GroupTypeIndex,
                })) as RemoteContext['groupTypes'],
            },
            3000
        )

        await jest.advanceTimersByTimeAsync(3000)

        const result = await settled
        expect(result?.failed).toBe(true)
        expect(result?.results.groups?.map((item) => item.id)).toEqual(['group-0-acme'])
    })
})
