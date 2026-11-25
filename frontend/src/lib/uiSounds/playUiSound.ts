import type { SoundName } from 'button-sounds'

import type { UiSound } from './uiSoundForTarget'

// The build copies the samples here, so the browser never calls the package's default CDN.
const SOUNDS_PATH = '/static/button-sounds'

const SOUND_NAMES: Record<UiSound, SoundName> = {
    click: 'hi75-soft',
    'toggle-on': 'lock-closed',
    'toggle-off': 'lock-open',
}

const VOLUME = 0.3

type ButtonSounds = typeof import('button-sounds')

let buttonSounds: Promise<ButtonSounds> | null = null

function loadButtonSounds(): Promise<ButtonSounds> {
    if (!buttonSounds) {
        buttonSounds = import('button-sounds').then(
            (module) => {
                module.setPath(SOUNDS_PATH)
                return module
            },
            (error) => {
                // A failed chunk download must not stick for the whole session, so the next press tries again.
                buttonSounds = null
                throw error
            }
        )
    }
    return buttonSounds
}

// Sounds are decoration, so a failed download or blocked playback stays silent instead of raising an error.
function withButtonSounds(use: (module: ButtonSounds) => void): void {
    loadButtonSounds()
        .then(use)
        .catch(() => {})
}

// A switch plays both of its samples over time, so reaching one loads the pair.
const WARM_UP_NAMES: Record<UiSound, SoundName[]> = {
    click: ['hi75-soft'],
    'toggle-on': ['lock-closed', 'lock-open'],
    'toggle-off': ['lock-closed', 'lock-open'],
}

/** Downloads the samples a control needs when the pointer reaches it, before the press that plays them. */
export function warmUpUiSound(sound: UiSound): void {
    withButtonSounds(({ load }) => WARM_UP_NAMES[sound].forEach((name) => load(name)))
}

export function playUiSound(sound: UiSound): void {
    const name = SOUND_NAMES[sound]
    withButtonSounds(({ press }) => press(name, { volume: VOLUME }))
    // A pointerup outside the component still releases it, so the release listens on the window. A cancelled
    // gesture, such as a touch that turns into a scroll, never releases, so it removes the listener instead.
    const gesture = new AbortController()
    window.addEventListener(
        'pointerup',
        () => {
            gesture.abort()
            withButtonSounds(({ release }) => release(name, { volume: VOLUME }))
        },
        { signal: gesture.signal }
    )
    window.addEventListener('pointercancel', () => gesture.abort(), { signal: gesture.signal })
}
