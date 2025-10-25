import fse from 'fs-extra'
import path from 'path'
import { fileURLToPath } from 'url'

import { isDev } from './utils.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

export function writeSourceCodeEditorTypes() {
    const readFile = (p) => {
        try {
            return fse.readFileSync(path.resolve(__dirname, p), { encoding: 'utf-8' })
        } catch (e) {
            if (isDev) {
                console.warn(`🙈 Didn't find "${p}" for the app source editor. Build it with: pnpm packages:build`)
            } else {
                throw e
            }
        }
    }
    const types = {
        '@types/react/index.d.ts': readFile('../node_modules/@types/react/index.d.ts'),
        '@types/react/global.d.ts': readFile('../node_modules/@types/react/global.d.ts'),
        '@types/kea/index.d.ts': readFile('../node_modules/kea/lib/index.d.ts'),
        '@posthog/lemon-ui/index.d.ts': readFile('./@posthog/lemon-ui/dist/index.d.ts'),
    }
    const packagesJsonFile = path.resolve(__dirname, './src/scenes/plugins/source/types/packages.json')
    fse.mkdirpSync(path.dirname(packagesJsonFile))
    fse.writeFileSync(packagesJsonFile, JSON.stringify(types, null, 4) + '\n')
}

writeSourceCodeEditorTypes()
