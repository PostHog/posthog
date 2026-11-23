// React Native with Hermes: Metro writes `.bundle` or `.jsbundle` files that get chunk IDs like
// JavaScript bundles. The Hermes compiler then composes a second map for the bytecode, and that
// composed map is what PostHog symbolicates with.

export const HERMES_BUNDLE_EXTENSIONS = ['.bundle', '.jsbundle'] as const

export function isHermesBundlePath(path: string): boolean {
    return HERMES_BUNDLE_EXTENSIONS.some((extension) => path.endsWith(extension))
}
