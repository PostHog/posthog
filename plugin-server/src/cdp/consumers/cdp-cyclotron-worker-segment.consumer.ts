import { Hub } from '~/types'

import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of segment plugins.
 */
export class CdpCyclotronWorkerSegment extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerSegment'

    constructor(hub: Hub) {
        super(hub, 'segment')
    }
}
