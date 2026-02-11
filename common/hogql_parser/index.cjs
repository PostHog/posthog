// CommonJS wrapper for the ES module WASM build
// This allows Jest and other CommonJS environments to import the module

module.exports = () => import('./hogql_parser_wasm.js').then(m => m.default);
module.exports.default = module.exports;
