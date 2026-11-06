import { Pool } from 'pg'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { UUIDT } from '~/common/utils/utils'
import { Hub } from '~/types'

import { decodeAttachments } from '../hogflows/transactional-email'
import { EmailAttachmentObjectStore } from './email-attachments-object-store'
import { EmailAttachmentsMissingError, EmailAttachmentsService } from './email-attachments.service'

class FakeObjectStore implements EmailAttachmentObjectStore {
    public objects = new Map<string, Buffer>()
    public failDeletes = false

    public put(key: string, content: Buffer): Promise<void> {
        this.objects.set(key, content)
        return Promise.resolve()
    }

    public get(key: string): Promise<Buffer | null> {
        return Promise.resolve(this.objects.get(key) ?? null)
    }

    public delete(keys: string[]): Promise<void> {
        if (this.failDeletes) {
            return Promise.reject(new Error('bucket unavailable'))
        }
        keys.forEach((key) => this.objects.delete(key))
        return Promise.resolve()
    }
}

describe('EmailAttachmentsService with object storage', () => {
    let hub: Hub
    let pool: Pool
    let objectStore: FakeObjectStore
    let service: EmailAttachmentsService
    const teamId = 1
    const files = decodeAttachments({
        tracking: { captureEngagement: false },
        attachments: [{ filename: 'report.pdf', content: Buffer.from('pdf bytes').toString('base64') }],
    })

    beforeAll(async () => {
        hub = await createHub({})
        pool = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
    })

    afterAll(async () => {
        await pool.end()
        await closeHub(hub)
    })

    beforeEach(() => {
        objectStore = new FakeObjectStore()
        service = new EmailAttachmentsService(hub.CYCLOTRON_NODE_DATABASE_URL, undefined, objectStore)
    })

    afterEach(async () => {
        await service.stop()
    })

    const rowsOf = async (jobId: string): Promise<{ content: Buffer | null; storage_key: string | null }[]> =>
        (await pool.query('SELECT content, storage_key FROM cyclotron_email_attachments WHERE job_id = $1', [jobId]))
            .rows

    it('keeps the bytes out of the database and reads them back', async () => {
        const jobId = new UUIDT().toString()

        await service.store(jobId, teamId, files)

        const rows = await rowsOf(jobId)
        expect(rows).toEqual([{ content: null, storage_key: `email-attachments/${teamId}/${jobId}/0` }])
        const loaded = await service.load(jobId, teamId, files)
        expect(loaded[0].content.toString()).toEqual('pdf bytes')
    })

    it.each([
        ['is gone', (store: FakeObjectStore) => store.objects.clear()],
        [
            'has changed',
            (store: FakeObjectStore) =>
                [...store.objects.keys()].forEach((key) => store.objects.set(key, Buffer.from('x'))),
        ],
    ])('refuses to send without the file when its object %s', async (_name, damage) => {
        const jobId = new UUIDT().toString()
        await service.store(jobId, teamId, files)

        damage(objectStore)

        await expect(service.load(jobId, teamId, files)).rejects.toBeInstanceOf(EmailAttachmentsMissingError)
    })

    it('deletes the object with its row, and keeps the row when the object cannot be deleted', async () => {
        const jobId = new UUIDT().toString()
        await service.store(jobId, teamId, files)

        objectStore.failDeletes = true
        await service.delete(jobId, teamId)
        expect(await rowsOf(jobId)).toHaveLength(1)
        expect(objectStore.objects.size).toEqual(1)

        objectStore.failDeletes = false
        await service.delete(jobId, teamId)
        expect(await rowsOf(jobId)).toHaveLength(0)
        expect(objectStore.objects.size).toEqual(0)
    })

    it('still reads a file stored in the database before the bucket was configured', async () => {
        const jobId = new UUIDT().toString()
        const withoutBucket = new EmailAttachmentsService(hub.CYCLOTRON_NODE_DATABASE_URL)
        await withoutBucket.store(jobId, teamId, files)
        await withoutBucket.stop()

        const loaded = await service.load(jobId, teamId, files)

        expect(loaded[0].content.toString()).toEqual('pdf bytes')
    })
})
