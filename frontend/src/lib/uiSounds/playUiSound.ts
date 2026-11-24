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

// A switch plays both of its samples over time, so reaching one loads the pair.
const WARM_UP_NAMES: Record<UiSound, SoundName[]> = {
    click: ['hi75-soft'],
    'toggle-on': ['lock-closed', 'lock-open'],
    'toggle-off': ['lock-closed', 'lock-open'],
}

/** Downloads the samples a control needs when the pointer reaches it, before the press that plays them. */
export function warmUpUiSound(sound: UiSound): void {
    void loadButtonSounds().then(({ load }) => WARM_UP_NAMES[sound].forEach((name) => load(name)))
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
