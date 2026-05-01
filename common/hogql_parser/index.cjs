// CommonJS wrapper using the CJS WASM build directly.
// This avoids import.meta.url and dynamic import() issues in Jest and other CJS environments.

const factory = require('./hogql_parser_wasm.cjs')

module.exports = factory
module.exports.default = factory
