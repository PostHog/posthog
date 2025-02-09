import { Reader, ReaderModel } from '@maxmind/geoip2-node'
import fetch from 'node-fetch'
import prettyBytes from 'pretty-bytes'
import { brotliDecompress } from 'zlib'

export const MMDB_ENDPOINT = 'https://mmdbcdn.posthog.net/'

import { Hub } from '../types'
import { status } from '../utils/status'

// TODO: Fix all of this to be super simple
export async function setupMmdb(hub: Hub): Promise<void> {
    if (!hub.DISABLE_MMDB) {
        // TODO: use local GeoLite2 on container at share/GeoLite2-City.mmdb instead of downloading it each time
        status.info('⏳', 'Downloading GeoLite2 database from PostHog servers...')
        const response = await fetch(MMDB_ENDPOINT, { compress: false })
        const filename = response.headers.get('content-disposition')!.match(/filename="(.+)"/)![1]
        const brotliContents = await response.buffer()
        status.info('✅', `Downloaded ${filename} of ${prettyBytes(brotliContents.byteLength)}`)

        hub.mmdb = await decompressAndOpenMmdb(brotliContents, filename)
    }
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
