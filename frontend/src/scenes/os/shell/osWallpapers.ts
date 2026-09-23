// pinned: wallpaper keys are saved in localStorage, so renaming one resets that choice
export type OsWallpaperKey = 'keyboard-garden' | 'hogzilla' | 'startup-monopoly' | 'office-party'

export interface OsWallpaperOption {
    key: OsWallpaperKey
    label: string
    /** Hover glow behind the desktop icons, matched to the artwork in light and dark mode. */
    glow: { light: string; dark: string }
    /** Busy artwork washes out plain white icon labels, so those labels get a dark backdrop. */
    labelBackdrop: boolean
}

// Glow colors are part of each artwork, so they stay fixed in both color modes.
export const OS_WALLPAPERS: OsWallpaperOption[] = [
    {
        key: 'keyboard-garden',
        label: 'Keyboard garden',
        glow: { light: '#53FFCB', dark: '#49BAC5' },
        labelBackdrop: false,
    },
    { key: 'hogzilla', label: 'Hogzilla', glow: { light: '#FF9528', dark: '#9370F0' }, labelBackdrop: true },
    {
        key: 'startup-monopoly',
        label: 'Startup monopoly',
        glow: { light: '#37B878', dark: '#96B4F0' },
        labelBackdrop: true,
    },
    { key: 'office-party', label: 'Office party', glow: { light: '#FF6E54', dark: '#D084F8' }, labelBackdrop: false },
]

export const DEFAULT_OS_WALLPAPER: OsWallpaperKey = 'keyboard-garden'

export function resolveOsWallpaper(stored: unknown): OsWallpaperOption {
    return (
        OS_WALLPAPERS.find(({ key }) => key === stored) ??
        (OS_WALLPAPERS.find(({ key }) => key === DEFAULT_OS_WALLPAPER) as OsWallpaperOption)
    )
}
