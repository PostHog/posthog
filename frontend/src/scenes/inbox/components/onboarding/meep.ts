import { lemonToast } from '@posthog/lemon-ui'

import meepUrl from 'public/sounds/meep.mp3'

let audio: HTMLAudioElement | null = null

/**
 * Onboarding sample cards render the *real* inbox card – "Review"/"Archive" buttons and all – so
 * users naturally try to act on them. There's no real report behind a sample, so a click can't
 * navigate; rather than leave the primary "Review" call-to-action looking broken, point the user at
 * the one setup command instead, with a cheeky "meep" sound as a nod to PostHog Code. Pure
 * onboarding flair; nothing else depends on it.
 */
export function playMeep(): void {
    // Plain string message so react-toastify dedupes rapid re-clicks (see lemonToast's ensureToastId).
    lemonToast.info("That's a sample. Run the setup command above to bring real pull requests and reports here.")
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
