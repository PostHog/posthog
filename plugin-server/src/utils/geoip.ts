import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import { join } from 'path'

import { PluginsServerConfig } from '../types'

export type GeoIp = {
    city: (ip: string) => City | null
}

export class GeoIPService {
    private _mmdbPromise: Promise<ReaderModel> | undefined

    constructor(private config: PluginsServerConfig) {}

    private getMmdb() {
        if (!this._mmdbPromise) {
            this._mmdbPromise = Reader.open(join(this.config.BASE_DIR, this.config.MMDB_FILE_LOCATION))
        }

        return this._mmdbPromise
    }

    async get(): Promise<GeoIp> {
        const mmdb = await this.getMmdb()

        return {
            city: (ip: string) => {
                if (typeof ip !== 'string') {
                    return null
                }
                try {
                    const res = mmdb.city(ip)
                    return res
                } catch (e) {
                    return null
                }
            },
        }
    }
}
