export interface Shortcut {
    use: string
    description: string
}

// Top-level names for a command inside a group, as `hog whoami` for `hog auth status`. hog runs the
// command a shortcut names, so its help, errors and usage events name that command. A Map, because
// the name comes from the command line, and an object lookup would also match `constructor`.
export const SHORTCUTS: ReadonlyMap<string, Shortcut> = new Map([
    ['whoami', { use: 'auth status', description: 'Show who hog is logged in as' }],
])
