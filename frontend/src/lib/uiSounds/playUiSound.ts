import type { SoundName } from 'button-sounds'

import type { UiSound } from './uiSoundForTarget'

// The build copies the samples here, so the browser never calls the package's default CDN.
const SOUNDS_PATH = '/static/button-sounds'

const SOUND_NAMES: Record<UiSound, SoundName> = {
    click: 'hi75-soft',
    'toggle-on': 'tonal-on',
    'toggle-off': 'tonal-off',
}

const VOLUME = 0.3

let buttonSounds: Promise<typeof import('button-sounds')> | null = null

function loadButtonSounds(): Promise<typeof import('button-sounds')> {
    if (!buttonSounds) {
        buttonSounds = import('button-sounds').then((module) => {
            module.setPath(SOUNDS_PATH)
            return module
        })
    }
    return buttonSounds
}

/** Fetches every sample up front, so the first press does not wait for its file to download. */
export function preloadUiSounds(): void {
    void loadButtonSounds().then(({ load }) => Object.values(SOUND_NAMES).forEach(load))
}

export function playUiSound(sound: UiSound): void {
    const name = SOUND_NAMES[sound]
    // A pointerup outside the component still releases it, so the release listens on the window.
    window.addEventListener(
        'pointerup',
        () => {
            void loadButtonSounds().then(({ release }) => release(name, { volume: VOLUME }))
        },
        { once: true }
    )
    void loadButtonSounds().then(({ press }) => press(name, { volume: VOLUME }))
}
