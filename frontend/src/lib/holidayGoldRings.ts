let goldRingsAudio: HTMLAudioElement | null = null
const optOutKey = 'christmas-gold-rings-muted'
const optOutPhrase = 'ihatexmas'
const sequenceTimeoutMs = 2_000

const isPlainKey = (event: KeyboardEvent): boolean =>
    event.key.length === 1 && !event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey

export function isGoldRingsMuted(): boolean {
    return sessionStorage.getItem(optOutKey) === 'true'
}

function playGoldRings(): void {
    goldRingsAudio ??= new Audio('/static/sounds/five-gold-rings.mp3')
    goldRingsAudio.pause()
    goldRingsAudio.currentTime = 0
    goldRingsAudio.volume = 0.5
    void goldRingsAudio.play().catch(() => undefined)
}

export function listenForGoldRingsKeys(isEnabled: () => boolean): () => void {
    let progress = 0
    let lastKeyAt = 0

    const trackOptOutKey = (key: string): boolean => {
        if (key === ' ') {
            return false
        }

        const now = Date.now()
        progress = now - lastKeyAt > sequenceTimeoutMs ? 0 : progress
        lastKeyAt = now
        const normalizedKey = key.toLowerCase()
        progress = normalizedKey === optOutPhrase[progress] ? progress + 1 : normalizedKey === optOutPhrase[0] ? 1 : 0

        if (progress === optOutPhrase.length) {
            sessionStorage.setItem(optOutKey, 'true')
            goldRingsAudio?.pause()
            progress = 0
            return true
        }
        return false
    }

    const onKeyDown = (event: KeyboardEvent): void => {
        if (!isEnabled() || isGoldRingsMuted() || !isPlainKey(event)) {
            return
        }
        if (event.target instanceof HTMLInputElement && event.target.type === 'password') {
            return
        }
        if (trackOptOutKey(event.key)) {
            return
        }

        if (event.key === '5') {
            playGoldRings()
        }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
}
