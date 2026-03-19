// unified v11's CallableInstance sets the prototype of the returned function
// to Processor.prototype via Object.setPrototypeOf, which drops
// Function.prototype from the chain. Sucrase's .call(void 0) transform then
// fails with "Cannot read properties of undefined (reading 'call')".
//
// We patch Object.setPrototypeOf to detect when a function's prototype is being
// set to something that lacks Function.prototype, and restore the chain.

const origSetPrototypeOf = Object.setPrototypeOf

Object.setPrototypeOf = function patchedSetPrototypeOf(obj, proto) {
    const result = origSetPrototypeOf.call(Object, obj, proto)
    // If `obj` is a function and it lost `.call`, fix the chain
    if (typeof obj === 'function' && typeof obj.call !== 'function') {
        // Walk up to find the end of the prototype chain (before null)
        let current = proto
        while (current && Object.getPrototypeOf(current) !== null) {
            current = Object.getPrototypeOf(current)
        }
        // Insert Function.prototype at the end of the chain
        if (current && current !== Function.prototype) {
            origSetPrototypeOf.call(Object, current, Function.prototype)
        }
    }
    return result
}

const { unified } = jest.requireActual('unified')

module.exports = { unified }
