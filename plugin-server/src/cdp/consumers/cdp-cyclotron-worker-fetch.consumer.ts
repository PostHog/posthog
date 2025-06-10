import { Hub } from '../../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerFetch extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerFetch'

    constructor(hub: Hub) {
        super(hub, 'fetch')
    }
}
