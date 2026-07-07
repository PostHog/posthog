import type { Plugin } from 'vite'

/**
 * Import `.sql` files as raw strings (e.g. `import query from './foo.sql'`).
 * The webpack build did this via `type: 'asset/source'`; Vite has no built-in
 * equivalent for a bare import (only the explicit `?raw` suffix), so map it here.
 */
export function sqlRawPlugin(): Plugin {
    return {
        name: 'posthog-storybook-sql-raw',
        transform(code, id) {
            if (!id.split('?')[0].endsWith('.sql')) {
                return null
            }
            return { code: `export default ${JSON.stringify(code)}`, map: null }
        },
    }
}
