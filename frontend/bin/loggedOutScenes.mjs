import fs from 'node:fs'
import path from 'node:path'

/**
 * The scenes a logged-out page can show: the scenes with `onlyUnauthenticated` or
 * `allowUnauthenticated` in scenes/scenes.ts that have a loader. The stable chunk build puts only
 * these scenes' chunks into the import map of a logged-out page. bin/loggedOutScenes.test.ts fails
 * when this list and scenes/scenes.ts disagree.
 */
export const LOGGED_OUT_SCENES = [
    'AgenticAccountMismatch',
    'AgenticAuthorize',
    'CodeCanvasLink',
    'CodeChannelLink',
    'CodeLoopLink',
    'CodeTaskLink',
    'InviteSignup',
    'Login',
    'Login2FA',
    'OAuthAuthorize',
    'OrganizationCreationConfirm',
    'PasswordReset',
    'PasswordResetComplete',
    'PreflightCheck',
    'Signup',
    'TwoFactorReset',
    'Unsubscribe',
    'VercelConnect',
    'VerifyEmail',
]

// The files that map a scene to its loader, as `[Scene.Name]: () => import('…')` or `Name: () => import('…')`.
const SCENE_REGISTRIES = ['src/scenes/appScenes.ts', 'src/productScenes.tsx']
const SCENE_LOADER = /(?:\[Scene\.(\w+)\]|(\w+)):\s*\(\)\s*=>\s*import\(\s*'([^']+)'\s*\)/g

/** A module path relative to the frontend directory, without its extension or a trailing `/index`. */
export function moduleKey(modulePath) {
    return path.posix
        .normalize(modulePath)
        .replace(/\.[cm]?[jt]sx?$/, '')
        .replace(/\/index$/, '')
}

// The tsconfig.json path aliases that scene loaders use, relative to the frontend directory.
const PATH_ALIASES = { 'products/': '../products/', 'scenes/': 'src/scenes/', 'lib/': 'src/lib/', '~/': 'src/' }

function resolveLoader(registry, specifier) {
    if (specifier.startsWith('.')) {
        return path.posix.join(path.posix.dirname(registry), specifier)
    }
    const alias = Object.keys(PATH_ALIASES).find((prefix) => specifier.startsWith(prefix))
    if (!alias) {
        throw new Error(`stable chunks: cannot resolve the scene loader '${specifier}' in ${registry}`)
    }
    return PATH_ALIASES[alias] + specifier.slice(alias.length)
}

/** Scene name -> module key of its loader, for every scene with a loader. */
export function sceneModules(frontendDir) {
    const modules = new Map()
    for (const registry of SCENE_REGISTRIES) {
        const source = fs.readFileSync(path.resolve(frontendDir, registry), 'utf8')
        for (const [, sceneEnumName, sceneKey, specifier] of source.matchAll(SCENE_LOADER)) {
            const modulePath = path.relative(frontendDir, path.resolve(frontendDir, resolveLoader(registry, specifier)))
            modules.set(sceneEnumName ?? sceneKey, moduleKey(modulePath.split(path.sep).join('/')))
        }
    }
    return modules
}
