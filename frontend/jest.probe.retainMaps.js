const v8 = require('v8')
const vm = require('vm')

// NODE_OPTIONS rejects this flag, so the probe sets it when the first test file of a worker starts.
v8.setFlagsFromString('--retain-maps-for-n-gc=0')

const FORCED_GC_ABOVE_HEAP_BYTES = 512 * 1024 * 1024

if (process.env.PROBE_FORCED_GC === '1' && process.memoryUsage().heapUsed > FORCED_GC_ABOVE_HEAP_BYTES) {
    v8.setFlagsFromString('--expose-gc')
    const gc = vm.runInNewContext('gc')
    v8.setFlagsFromString('--no-expose-gc')
    gc()
}
