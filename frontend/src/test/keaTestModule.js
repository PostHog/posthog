const kea = require('../../node_modules/kea')
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
