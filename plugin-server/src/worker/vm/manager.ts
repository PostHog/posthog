import { Hub } from 'types'

import { LazyPluginVM } from './lazy'

export class LazyPluginVmManager {
    vmsList: LazyPluginVM[]
    nextVmIndex: number
    stateless: boolean

    constructor(server: Hub, stateless = false) {
        this.stateless = stateless
        this.nextVmIndex = 0
        this.vmsList = []
        const maxVms = stateless ? server.TASKS_PER_WORKER * 2 : 1

        for (let i = 0; i < maxVms; ++i) {
            this.vmsList.push(new LazyPluginVM())
        }
    }

    getVm(): LazyPluginVM {
        if (!this.stateless) {
            return this.vmsList[0]
        }

        if (this.nextVmIndex >= this.vmsList.length) {
            this.nextVmIndex = 0
        }
        const vm = this.vmsList[this.nextVmIndex]
        ++this.nextVmIndex

        return vm
    }
}
