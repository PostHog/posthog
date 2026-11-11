import { kea, path } from 'kea'
import { getDisposables } from 'kea-disposables'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { initKeaTests } from '~/test/init'

import { ActivityQueryRequest } from './activityQueryRequest'

jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => {
    const { ConcurrencyController } = jest.requireActual<typeof import('lib/utils/concurrencyController')>(
        'lib/utils/concurrencyController'
    )
    return { concurrencyController: new ConcurrencyController(1), cancelQueryOnServer: jest.fn() }
})

describe('ActivityQueryRequest', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(cancelQueryOnServer).mockClear()
    })

    it('shares a query limit across requests and never starts a disposed queued request', async () => {
        const logic = kea([path(['tests', 'activityQueryRequest'])]).build()
        const unmount = logic.mount()
        try {
            const disposables = getDisposables(logic)
            const first = new ActivityQueryRequest(disposables, 'first', 1)
            const queued = new ActivityQueryRequest(disposables, 'queued', 1)
            const last = new ActivityQueryRequest(disposables, 'last', 1)
            const started: string[] = []
            let finishFirst!: (value: string) => void
            const firstResult = first.run(() => {
                started.push('first')
                return new Promise<string>((resolve) => {
                    finishFirst = resolve
                })
            })
            const queuedResult = queued.run(async () => {
                started.push('queued')
                return 'queued'
            })
            const lastResult = last.run(async () => {
                started.push('last')
                return 'last'
            })
            expect(started).toEqual(['first'])
            disposables.dispose('queued')
            await expect(queuedResult).rejects.toMatchObject({ name: 'AbortError' })
            finishFirst('first')
            expect(await firstResult).toBe('first')
            expect(await lastResult).toBe('last')
            expect(started).toEqual(['first', 'last'])
            expect(cancelQueryOnServer).not.toHaveBeenCalled()
        } finally {
            unmount()
        }
    })
})
