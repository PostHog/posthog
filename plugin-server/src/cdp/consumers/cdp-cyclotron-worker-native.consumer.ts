import { Hub } from '~/types'

import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of native plugins.
 */
export class CdpCyclotronWorkerNative extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerNative'

    constructor(hub: Hub) {
        super(hub, 'native')
    }
}
