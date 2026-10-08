import { GROUPS_OUTPUT, PERSONS_OUTPUT } from '~/common/outputs'
import { GroupFlushResult } from '~/ingestion/common/groups/group-store.interface'

import { IngestionApiServer } from './ingestion-api-server'

describe('IngestionApiServer', () => {
    let server: IngestionApiServer

    beforeEach(() => {
        server = new IngestionApiServer()
    })

    it('reports healthy before any failure', () => {
        expect((server as any).isHealthy().status).toBe('ok')
    })

    describe('cleanup', () => {
        // groupStore.flush() no longer produces ClickHouse messages itself (see
        // batch-writing-group-store.ts) — it returns them for the caller to
        // produce, mirroring personsStore.flushAndProduceMessages(). The shutdown
        // cleanup path must produce them itself or dirty entries flushed at
        // shutdown (e.g. a pod drain mid-batch) are written to Postgres but never
        // reach ClickHouse, and a redelivery of the same batch finds no property
        // diff and never regenerates the message.
        it('produces ClickHouse messages returned by groupStore.flush() during shutdown cleanup', async () => {
            const flushResult: GroupFlushResult = {
                messages: [{ output: GROUPS_OUTPUT, value: Buffer.from('group-payload') }],
                teamId: 1,
                groupTypeIndex: 0,
                groupKey: 'test-group',
            }
            const groupStore = {
                flush: jest.fn().mockResolvedValue([flushResult]),
                shutdown: jest.fn().mockResolvedValue(undefined),
            }
            const ingestionOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
            ;(server as any).groupStore = groupStore
            ;(server as any).ingestionOutputs = ingestionOutputs

            await (server as any).drainStores()

            expect(ingestionOutputs.produce).toHaveBeenCalledWith(GROUPS_OUTPUT, {
                key: null,
                value: flushResult.messages[0].value,
                teamId: flushResult.teamId,
            })
        })

        // In shadow mode the pipeline's persons store is the router, whose flush seals and writes the shadow
        // segments the Postgres decision closes. A drain through the raw Postgres store writes Postgres only, so
        // every person with a group pending at the stop ends one group ahead on Postgres.
        it('drains the pipeline persons store at shutdown and produces its messages, not the raw Postgres store', async () => {
            const message = { output: PERSONS_OUTPUT, value: Buffer.from('person-payload') }
            const personsStore = {
                flush: jest.fn().mockResolvedValue([]),
                shutdown: jest.fn().mockResolvedValue(undefined),
            }
            const pipelinePersonsStore = {
                flush: jest.fn().mockResolvedValue([{ messages: [message], teamId: 1, distinctId: 'd1', uuid: 'u1' }]),
                shutdown: jest.fn().mockResolvedValue(undefined),
            }
            const ingestionOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
            ;(server as any).personsStore = personsStore
            ;(server as any).pipelinePersonsStore = pipelinePersonsStore
            ;(server as any).ingestionOutputs = ingestionOutputs

            await (server as any).drainStores()

            expect(pipelinePersonsStore.flush).toHaveBeenCalledTimes(1)
            expect(personsStore.flush).not.toHaveBeenCalled()
            expect(ingestionOutputs.produce).toHaveBeenCalledWith(PERSONS_OUTPUT, {
                key: null,
                value: message.value,
                teamId: 1,
            })
            expect(pipelinePersonsStore.shutdown).toHaveBeenCalledTimes(1)
        })
    })
})
