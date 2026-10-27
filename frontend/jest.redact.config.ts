// Experimental: runs Jest with React swapped for TanStack Redact. See plugins/redact.mjs.
// Usage: pnpm jest -c jest.redact.config.ts <paths>
import base from './jest.config'

const R = '<rootDir>/node_modules/@tanstack/redact/dist'
const config = {
    ...base,
    moduleNameMapper: {
        '^use-sync-external-store(/shim)?(/with-selector)?(/index)?(\\.js)?$': `${R}/react/index.js`,
        '^react/jsx-runtime$': `${R}/react/jsx-runtime.js`,
        '^react/jsx-dev-runtime$': `${R}/react/jsx-runtime.js`,
        '^react-dom/client$': `${R}/dom/client.js`,
        '^react-dom/server(\\.browser)?$': `${R}/server/index.js`,
        '^react-dom/test-utils$': `${R}/dom/test-utils.js`,
        '^react-dom$': `${R}/dom/index.js`,
        '^react$': `${R}/react/index.js`,
        '^scheduler$': `${R}/scheduler/index.js`,
        ...base.moduleNameMapper,
    },
    transformIgnorePatterns: [String(base.transformIgnorePatterns?.[0]).replace('(?!.*(', '(?!.*(@tanstack/redact|')],
}
export default config
