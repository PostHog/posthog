import meepUrl from 'public/sounds/meep.mp3'

let audio: HTMLAudioElement | null = null

/**
 * Cheeky audio easter egg for the onboarding previews: clicking an (otherwise inert) sample card
 * plays a "meep" – a nod to PostHog Desktop. Pure flair. The visible response to the click (scrolling
 * to and flashing the setup command) is the caller's job, so this no longer pops a corner toast the
 * user isn't looking at.
 */
export function playMeep(): void {
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
