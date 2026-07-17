import { lemonToast } from '@posthog/lemon-ui'

import meepUrl from 'public/sounds/meep.mp3'

let audio: HTMLAudioElement | null = null

/**
 * Cheeky easter egg for the onboarding previews: clicking the (otherwise inert) sample cards plays
 * a "meep" and pops a matching toast – a nod to PostHog Code. Pure flair; nothing else depends on it.
 */
export function playMeep(): void {
    lemonToast.info('Meep')
    try {
        // Reuse one element across clicks; rewind so rapid clicks restart the sound rather than overlap.
        if (!audio) {
            audio = new Audio(meepUrl)
            audio.volume = 0.8
        }
        audio.currentTime = 0
        // Autoplay can be blocked until the page has been interacted with; a click satisfies that,
        // but ignore any rejection (and jsdom, which doesn't implement playback) regardless.
        void audio.play().catch(() => {})
    } catch {
        // Audio unsupported in this environment – the toast alone is fine.
    }
}
