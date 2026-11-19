// Top-level names for a command inside a group, as `hog whoami` for `hog auth status`. hog runs the
// command a shortcut names, so its help, errors and usage events name that command.
export const SHORTCUTS: Readonly<Record<string, { use: string; description: string }>> = {
    whoami: { use: 'auth status', description: 'Show who hog is logged in as' },
}
