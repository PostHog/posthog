import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fetch from 'node-fetch'
import prettyBytes from 'pretty-bytes'
import { brotliDecompress } from 'zlib'

import { PluginsServerConfig } from '../types'
import { status } from './status'

const MMDB_ENDPOINT = 'https://mmdbcdn.posthog.net/'

const brotliDecompressAsync = (brotliContents: ArrayBuffer): Promise<Buffer> =>
    new Promise((resolve, reject) => {
        brotliDecompress(brotliContents, (error, result) => (error ? reject(error) : resolve(result)))
    })

export type GeoIp = {
    city: (ip: string) => City | null
}

export class GeoIPService {
    private _mmdbPromise: Promise<ReaderModel> | undefined

    constructor(private config: PluginsServerConfig) {}

    private getMmdb() {
        // TODO: Add config option to use from disk instead
        if (this._mmdbPromise) {
            return this._mmdbPromise
        }

        this._mmdbPromise = (async () => {
            // TODO: use local GeoLite2 on container at share/GeoLite2-City.mmdb instead of downloading it each time
            status.info('⏳', 'Downloading GeoLite2 database from PostHog servers...')
            const response = await fetch(MMDB_ENDPOINT, { compress: false })
            const filename = response.headers.get('content-disposition')!.match(/filename="(.+)"/)![1]
            const brotliContents = await response.arrayBuffer()
            const decompressed = await brotliDecompressAsync(brotliContents)

            status.info(
                '🪗',
                `Decompressed ${filename} from ${prettyBytes(brotliContents.byteLength)} into ${prettyBytes(
                    decompressed.byteLength
                )}`
            )

            return Reader.openBuffer(decompressed)
        })()

        return this._mmdbPromise
    }

    async get(): Promise<GeoIp> {
        const mmdb = await this.getMmdb()

        return {
            city: (ip: string) => {
                if (typeof ip !== 'string') {
                    return null
                }
                return mmdb?.city(ip) ?? null
            },
        }
    }
}
