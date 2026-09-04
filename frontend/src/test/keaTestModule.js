const kea = require('../../node_modules/kea')
const { testListeners } = require('./keaTestListeners')

module.exports = { ...kea, __esModule: true, listeners: testListeners(kea.listeners) }
