import { Reader, ReaderModel } from '@maxmind/geoip2-node'
import { captureException } from '@sentry/minimal'
import { DateTime } from 'luxon'
import net from 'net'
import { AddressInfo } from 'net'
import fetch from 'node-fetch'
import prettyBytes from 'pretty-bytes'
import { serialize } from 'v8'
import { brotliDecompress } from 'zlib'

import {
    MMDB_ATTACHMENT_KEY,
    MMDB_ENDPOINT,
    MMDB_INTERNAL_SERVER_TIMEOUT_SECONDS,
    MMDB_STALE_AGE_DAYS,
    MMDB_STATUS_REDIS_KEY,
    MMDBRequestStatus,
} from '../../config/mmdb-constants'
import { Hub, PluginAttachmentDB } from '../../types'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'
import { ServerInstance } from '../pluginsServer'

type MMDBPrepServerInstance = Pick<ServerInstance, 'hub' | 'mmdb'>

enum MMDBFileStatus {
    Idle = 'idle',
    Fetching = 'fetching',
    Unavailable = 'unavailable',
}

/** Check if MMDB is being currently fetched by any other plugin server worker in the cluster. */
async function getMmdbStatus(hub: Hub): Promise<MMDBFileStatus> {
    return (await hub.db.redisGet(MMDB_STATUS_REDIS_KEY, MMDBFileStatus.Idle)) as MMDBFileStatus
}

/** Decompress a Brotli-compressed MMDB buffer and open a reader from it. */
async function decompressAndOpenMmdb(brotliContents: Buffer, filename: string): Promise<ReaderModel> {
    return await new Promise((resolve, reject) => {
        brotliDecompress(brotliContents, (error, result) => {
            if (error) {
                reject(error)
            } else {
                status.info(
                    '🪗',
                    `Decompressed ${filename} from ${prettyBytes(brotliContents.byteLength)} into ${prettyBytes(
                        result.byteLength
                    )}`
                )
                try {
                    resolve(Reader.openBuffer(result))
                } catch (e) {
                    reject(e)
                }
            }
        })
    })
}

/** Download latest MMDB database, save it, and return its reader. */
async function fetchAndInsertFreshMmdb(hub: Hub): Promise<ReaderModel> {
    const { db } = hub

    status.info('⏳', 'Downloading GeoLite2 database from PostHog servers...')
    const response = await fetch(MMDB_ENDPOINT, { compress: false })
    const contentType = response.headers.get('content-type')
    const filename = response.headers.get('content-disposition')!.match(/filename="(.+)"/)![1]
    const brotliContents = await response.buffer()
    status.info('✅', `Downloaded ${filename} of ${prettyBytes(brotliContents.byteLength)}`)

    // Insert new attachment
    const newAttachmentResults = await db.postgresQuery<PluginAttachmentDB>(
        `
        INSERT INTO posthog_pluginattachment (
            key, content_type, file_name, file_size, contents, plugin_config_id, team_id
        ) VALUES ($1, $2, $3, $4, $5, NULL, NULL) RETURNING *
    `,
        [MMDB_ATTACHMENT_KEY, contentType, filename + '.br', brotliContents.byteLength, brotliContents],
        'insertGeoIpAttachment'
    )
    // Ensure that there's no old attachments lingering
    await db.postgresQuery(
        `
        DELETE FROM posthog_pluginattachment WHERE key = $1 AND id != $2
    `,
        [MMDB_ATTACHMENT_KEY, newAttachmentResults.rows[0].id],
        'deleteGeoIpAttachment'
    )
    status.info('💾', `Saved ${filename} into the database`)

    return await decompressAndOpenMmdb(brotliContents, filename)
}

/** Drop-in replacement for fetchAndInsertFreshMmdb that handles multiple worker concurrency better. */
async function distributableFetchAndInsertFreshMmdb(
    serverInstance: MMDBPrepServerInstance
): Promise<ReaderModel | null> {
    const { hub } = serverInstance
    let fetchingStatus = await getMmdbStatus(hub)
    if (fetchingStatus === MMDBFileStatus.Unavailable) {
        status.info(
            '☹️',
            'MMDB fetch and insert for GeoIP capabilities is currently unavailable in this PostHog instance - IP location data may be stale or unavailable'
        )
        return null
    }
    if (fetchingStatus === MMDBFileStatus.Fetching) {
        while (fetchingStatus === MMDBFileStatus.Fetching) {
            // Retrying shortly, when perhaps the MMDB has been fetched somewhere else and the attachment is up to date
            // Only one plugin server thread out of instances*(workers+1) needs to download the file this way
            await delay(200)
            fetchingStatus = await getMmdbStatus(hub)
        }
        return prepareMmdb(serverInstance)
    }
    // Allow 120 seconds of download until another worker retries
    await hub.db.redisSet(MMDB_STATUS_REDIS_KEY, MMDBFileStatus.Fetching, 120)
    try {
        const mmdb = await fetchAndInsertFreshMmdb(hub)
        await hub.db.redisSet(MMDB_STATUS_REDIS_KEY, MMDBFileStatus.Idle)
        return mmdb
    } catch (e) {
        // In case of an error mark the MMDB feature unavailable for an hour
        await hub.db.redisSet(MMDB_STATUS_REDIS_KEY, MMDBFileStatus.Unavailable, 120)
        status.error('❌', 'An error occurred during MMDB fetch and insert:', e)
        return null
    }
}

/** Update server MMDB in the background, with no availability interruptions. */
async function backgroundInjectFreshMmdb(serverInstance: MMDBPrepServerInstance): Promise<void> {
    const mmdb = await distributableFetchAndInsertFreshMmdb(serverInstance)
    if (mmdb) {
        serverInstance.mmdb = mmdb
        status.info('💉', `Injected fresh ${MMDB_ATTACHMENT_KEY}`)
    }
}

/** Ensure that an MMDB is available and return its reader. If needed, update the MMDB in the background. */
export async function prepareMmdb(
    serverInstance: MMDBPrepServerInstance,
    onlyBackground?: false
): Promise<ReaderModel | null>
export async function prepareMmdb(serverInstance: MMDBPrepServerInstance, onlyBackground: true): Promise<boolean>
export async function prepareMmdb(
    serverInstance: MMDBPrepServerInstance,
    onlyBackground = false
): Promise<ReaderModel | null | boolean> {
    const { hub } = serverInstance
    const { db } = hub

    const readResults = await db.postgresQuery<PluginAttachmentDB>(
        `
        SELECT * FROM posthog_pluginattachment
        WHERE key = $1 AND plugin_config_id IS NULL AND team_id IS NULL
        ORDER BY file_name ASC
    `,
        [MMDB_ATTACHMENT_KEY],
        'fetchGeoIpAttachment'
    )
    if (!readResults.rowCount) {
        status.info('⬇️', `Fetching ${MMDB_ATTACHMENT_KEY} for the first time`)
        if (onlyBackground) {
            await backgroundInjectFreshMmdb(serverInstance)
            return true
        } else {
            const mmdb = await distributableFetchAndInsertFreshMmdb(serverInstance)
            if (!mmdb) {
                status.warn('🤒', 'Because of MMDB unavailability, GeoIP plugins will fail in this PostHog instance')
            }
            return mmdb
        }
    }
    const [mmdbRow] = readResults.rows
    if (!mmdbRow.contents) {
        throw new Error(`${MMDB_ATTACHMENT_KEY} attachment ID ${mmdbRow.id} has no file contents!`)
    }

    const mmdbDateStringMatch = mmdbRow.file_name.match(/\d{4}-\d{2}-\d{2}/)
    if (!mmdbDateStringMatch) {
        throw new Error(
            `${MMDB_ATTACHMENT_KEY} attachment ID ${mmdbRow.id} has an invalid filename! ${MMDB_ATTACHMENT_KEY} filename must include an ISO date`
        )
    }
    const mmdbAge = Math.round(-DateTime.fromISO(mmdbDateStringMatch[0]).diffNow().as('days'))
    if (mmdbAge > MMDB_STALE_AGE_DAYS) {
        status.info(
            '🔁',
            `${MMDB_ATTACHMENT_KEY} is ${mmdbAge} ${
                mmdbAge === 1 ? 'day' : 'days'
            } old, which is more than the staleness threshold of ${MMDB_STALE_AGE_DAYS} days, refreshing in the background...`
        )
        if (onlyBackground) {
            await backgroundInjectFreshMmdb(serverInstance)
            return true
        } else {
            void backgroundInjectFreshMmdb(serverInstance)
        }
    }

    if (onlyBackground) {
        return false
    } else {
        return await decompressAndOpenMmdb(mmdbRow.contents, mmdbRow.file_name)
    }
}

/** Check for MMDB staleness every 4 hours, if needed perform a no-interruption update. */
export async function performMmdbStalenessCheck(serverInstance: MMDBPrepServerInstance): Promise<void> {
    status.info('⏲', 'Performing periodic MMDB staleness check...')
    const wasUpdatePerformed = await prepareMmdb(serverInstance, true)
    if (wasUpdatePerformed) {
        status.info('✅', 'MMDB staleness check completed, update performed')
    } else {
        status.info('❎', 'MMDB staleness check completed, no update was needed')
    }
}

export async function createMmdbServer(serverInstance: MMDBPrepServerInstance): Promise<net.Server> {
    status.info('🗺', 'Starting internal MMDB server...')
    const mmdbServer = net.createServer((socket) => {
        socket.setEncoding('utf8')

        let status: MMDBRequestStatus = MMDBRequestStatus.OK

        socket.on('data', (partialData) => {
            // partialData SHOULD be an IP address string
            let responseData: any
            if (status === MMDBRequestStatus.OK) {
                if (serverInstance.mmdb) {
                    try {
                        responseData = serverInstance.mmdb.city(partialData.toString().trim())
                    } catch (e) {
                        responseData = null
                    }
                } else {
                    captureException(new Error(status))
                    status = MMDBRequestStatus.ServiceUnavailable
                }
            }
            if (status !== MMDBRequestStatus.OK) {
                responseData = status
            }
            socket.write(serialize(responseData ?? null))
        })

        socket.setTimeout(MMDB_INTERNAL_SERVER_TIMEOUT_SECONDS * 1000).on('timeout', () => {
            captureException(new Error(status))
            status = MMDBRequestStatus.TimedOut
            socket.emit('end')
        })

        socket.once('end', () => {
            if (status !== MMDBRequestStatus.OK) {
                socket.write(serialize(status))
            }
            socket.destroy()
        })
    })

    mmdbServer.on('error', (error) => {
        captureException(error)
    })

    return new Promise((resolve, reject) => {
        const rejectTimeout = setTimeout(
            () => reject(new Error('Internal MMDB server could not start listening!')),
            3000
        )
        mmdbServer.listen(serverInstance.hub.INTERNAL_MMDB_SERVER_PORT, 'localhost', () => {
            const port = (mmdbServer.address() as AddressInfo).port
            status.info('👂', `Internal MMDB server listening on port ${port}`)
            clearTimeout(rejectTimeout)
            resolve(mmdbServer)
        })
    })
}
