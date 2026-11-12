import { dirname } from 'node:path'
import { z } from 'zod'

import { parseJsonOrUndefined } from '@/core/json'
import { hogFile, isInside } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

// A `script` install carries the receipt install.sh writes. A `standalone` one is a binary placed by hand.
export type InstallKind =
    | 'script'
    | 'standalone'
    | 'homebrew'
    | 'npm-global'
    | 'pnpm-global'
    | 'bun-global'
    | 'npx'
    | 'project'
    | 'source'

export interface InstallMethod {
    kind: InstallKind
    path: string
    project?: string
}

export const RECEIPT_FILE = 'install.json'

const Receipt = z.looseObject({ method: z.literal('script'), install_dir: z.string() })

const PACKAGE = '@posthog/hog'

// The first match wins, so the runner caches and global folders come before a project's node_modules.
const NODE_LAYOUTS: readonly [kind: InstallKind, pattern: RegExp][] = [
    ['npx', /\/_npx\/|\/dlx\/|\/bunx-[^/]*\//],
    ['bun-global', /\/\.bun\/install\/global\//],
    ['pnpm-global', /\/pnpm\/global\/|\/pnpm-global\//],
    // npm's prefix: lib/node_modules on macOS and Linux, including nvm's, and npm/node_modules on Windows.
    ['npm-global', /\/lib\/node_modules\/|\/npm\/node_modules\//],
]

export function classifyPath(path: string): Pick<InstallMethod, 'kind' | 'project'> | undefined {
    const normalized = path.replaceAll('\\', '/')
    if (/\/Cellar\//.test(normalized)) {
        return { kind: 'homebrew' }
    }
    if (!normalized.includes('/node_modules/')) {
        return undefined
    }
    for (const [kind, pattern] of NODE_LAYOUTS) {
        if (pattern.test(normalized)) {
            return { kind }
        }
    }
    return { kind: 'project', project: path.slice(0, normalized.indexOf('/node_modules/')) }
}

async function receiptOwns(runtime: Runtime, executable: string): Promise<boolean> {
    try {
        const receipt = parseJsonOrUndefined(await runtime.readFile(hogFile(runtime, RECEIPT_FILE)), Receipt)
        if (!receipt) {
            return false
        }
        const folder = await runtime.realPath(receipt.install_dir)
        return dirname(executable) === folder || isInside(folder, executable)
    } catch {
        return false
    }
}

export async function detectInstallMethod(runtime: Runtime): Promise<InstallMethod> {
    if (runtime.isDevelopment) {
        return { kind: 'source', path: runtime.execPath }
    }

    const path = await runtime.realPath(runtime.execPath).catch(() => runtime.execPath)
    const byPath = classifyPath(path)
    if (byPath) {
        return { ...byPath, path }
    }

    return { kind: (await receiptOwns(runtime, path)) ? 'script' : 'standalone', path }
}

// Undefined for a project dependency and a checkout, which no single command updates.
export function upgradeCommand(method: InstallMethod, version?: string): string | undefined {
    const spec = `${PACKAGE}@${version ?? 'latest'}`
    switch (method.kind) {
        case 'script':
        case 'standalone':
            return version ? `hog upgrade --version ${version}` : 'hog upgrade'
        case 'homebrew':
            return 'brew upgrade hog'
        case 'npm-global':
            return `npm install -g ${spec}`
        case 'pnpm-global':
            return `pnpm add -g ${spec}`
        case 'bun-global':
            return `bun add -g ${spec}`
        case 'npx':
            return `npx ${spec}`
        case 'project':
        case 'source':
            return undefined
    }
}

export function upgradeAdvice(method: InstallMethod, rerun: string): string {
    switch (method.kind) {
        case 'npx':
            return `Run \`npx ${PACKAGE}@latest ${rerun}\` to use the latest version.`
        case 'project':
            return `This hog is a dependency of ${method.project}. Update ${PACKAGE} in its package.json, or run \`npx ${PACKAGE}@latest ${rerun}\`.`
        case 'source':
            return 'This hog runs from source. Pull the latest changes.'
        default:
            return `Run \`${upgradeCommand(method)}\`, then run \`hog ${rerun}\` again.`
    }
}
