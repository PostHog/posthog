// unified's CallableInstance pattern breaks Sucrase's .call(void 0) transform.
// This wrapper re-exports unified using dynamic import (ESM-native) and patches
// the callable instance so Function.prototype.call is available.
//
// Instead of transforming unified through Sucrase, we point moduleNameMapper here.

const { unified: originalUnified, Processor } = jest.requireActual('unified')

// The CallableInstance sets prototype to Processor.prototype, dropping
// Function.prototype from the chain. Restore it so .call/.apply/.bind work.
function patchCallable(obj) {
    if (typeof obj === 'function' && typeof obj.call !== 'function') {
        const proto = Object.getPrototypeOf(obj)
        // Insert Function.prototype between the object and its current prototype
        Object.setPrototypeOf(proto, Function.prototype)
    }
    return obj
}

const unified = patchCallable(originalUnified)

module.exports = { unified, Processor }
