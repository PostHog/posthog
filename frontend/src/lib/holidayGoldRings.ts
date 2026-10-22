let goldRingsAudio: HTMLAudioElement | null = null
const optOutKey = 'christmas-gold-rings-muted'
const optOutPhrase = 'ihatexmas'
const sequenceTimeoutMs = 2_000

const isPlainKey = (event: KeyboardEvent): boolean =>
    event.key.length === 1 && !event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey

export function isGoldRingsMuted(): boolean {
    return sessionStorage.getItem(optOutKey) === 'true'
}

function isGoldRingsActive(date: Date): boolean {
    const month = date.getMonth()
    const day = date.getDate()
    return (month === 11 && day >= 25) || (month === 0 && day <= 5)
}

function playGoldRings(): void {
    goldRingsAudio ??= new Audio('/static/sounds/five-gold-rings.mp3')
    goldRingsAudio.pause()
    goldRingsAudio.currentTime = 0
    goldRingsAudio.volume = 0.5
    void goldRingsAudio.play().catch(() => undefined)
}

function isEditableTarget(event: KeyboardEvent): boolean {
    const target = event.composedPath()[0]
    return (
        target instanceof HTMLElement && !!target.closest('input, textarea, select, [contenteditable], .monaco-editor')
    )
}

export function listenForGoldRingsKeys(isEnabled: () => boolean): () => void {
    let progress = 0
    let lastKeyAt = 0

    const onKeyDown = (event: KeyboardEvent): void => {
        if (!isEnabled() || isGoldRingsMuted() || !isPlainKey(event)) {
            return
        }
        if (event.target instanceof HTMLInputElement && event.target.type === 'password') {
            return
        }

        if (event.key !== ' ') {
            const now = Date.now()
            progress = now - lastKeyAt > sequenceTimeoutMs ? 0 : progress
            lastKeyAt = now
            const key = event.key.toLowerCase()
            progress = key === optOutPhrase[progress] ? progress + 1 : key === optOutPhrase[0] ? 1 : 0

            if (progress === optOutPhrase.length) {
                sessionStorage.setItem(optOutKey, 'true')
                goldRingsAudio?.pause()
                progress = 0
                return
            }
        }

        if (event.key === '5' && !isEditableTarget(event) && isGoldRingsActive(new Date())) {
            playGoldRings()
        }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
}
