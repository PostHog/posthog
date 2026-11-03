// KEA_IMPL=wasm runs the tests on packages/kea-wasm, a port with its reducer engine in Rust.
const kea =
    process.env.KEA_IMPL === 'wasm'
        ? require('../../../packages/kea-wasm/dist/index.cjs.js')
        : require('../../node_modules/kea')
const { testListenerDefinitions, testListeners } = require('./keaTestListeners')

function wrapLogicInput(input) {
    if (!input || typeof input !== 'object' || input.listeners === undefined) {
        return input
    }
    return { ...input, listeners: testListenerDefinitions(input.listeners) }
}

function testKea(input) {
    return kea.kea(Array.isArray(input) ? input.map(wrapLogicInput) : wrapLogicInput(input))
}

/** @type {typeof kea & { __esModule: true }} */
module.exports = { ...kea, __esModule: true, kea: testKea, listeners: testListeners(kea.listeners) }
