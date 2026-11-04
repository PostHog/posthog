import { isAbsolute, posix, relative, resolve, win32 } from 'node:path'

import { HogError } from './errors'
import type { Runtime } from './runtime'

export function absolutePath(root: string, path: string): string {
    return isAbsolute(path) ? path : resolve(root, path)
}

// The path to store in posthog.json, relative to its folder. A sibling folder stays relative, as
// posthog-cli stored it, so the file works in any checkout.
export function storedPath(root: string, path: string): string {
    const rel = relative(root, path)
    return isAbsolute(rel) ? path : rel
}

// hog's own folder, where it keeps its settings, the approvals it waits for and, without a keychain,
// its credentials. posthog-cli's ~/.posthog folder is not hog's: only `hog auth migrate` reads it.
export function hogDir(runtime: Pick<Runtime, 'env' | 'platform' | 'homeDir' | 'isDevelopment'>): string {
    const { env, platform } = runtime
    const home = runtime.homeDir()
    const name = runtime.isDevelopment ? 'hog-dev' : 'hog'
    let folder: string | undefined
    if (platform === 'win32') {
        // Local, not Roaming: a domain profile copies Roaming to a server and to every machine the
        // person signs in to, and this folder can hold credentials.
        folder = env.LOCALAPPDATA
            ? win32.join(env.LOCALAPPDATA, name)
            : home && win32.join(home, 'AppData', 'Local', name)
    } else if (platform === 'darwin') {
        folder = home && posix.join(home, 'Library', 'Application Support', name)
    } else {
        // The XDG spec says to ignore a relative XDG_CONFIG_HOME.
        const xdg = env.XDG_CONFIG_HOME && posix.isAbsolute(env.XDG_CONFIG_HOME) ? env.XDG_CONFIG_HOME : undefined
        folder = xdg ? posix.join(xdg, name) : home && posix.join(home, '.config', name)
    }
    if (!folder) {
        throw new HogError(
            'no_home_directory',
            "hog couldn't find your home folder to keep its settings in.",
            platform === 'win32' ? 'Set LOCALAPPDATA to your local app data folder.' : 'Set HOME to your home folder.'
        )
    }
    return folder
}

export function hogFile(
    runtime: Pick<Runtime, 'env' | 'platform' | 'homeDir' | 'isDevelopment'>,
    name: string
): string {
    const folder = hogDir(runtime)
    return runtime.platform === 'win32' ? win32.join(folder, name) : posix.join(folder, name)
}
