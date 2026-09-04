const kea = require('../../node_modules/kea')
const { testListeners } = require('./keaTestListeners')

/** @type {typeof kea & { __esModule: true }} */
module.exports = { ...kea, __esModule: true, listeners: testListeners(kea.listeners) }
