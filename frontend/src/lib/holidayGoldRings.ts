let goldRingsAudio: HTMLAudioElement | null = null

export function isGoldRingsActive(date: Date, enabled: boolean): boolean {
    const month = date.getMonth()
    const day = date.getDate()
    const isTwelveDaysOfChristmas = (month === 11 && day >= 25) || (month === 0 && day <= 5)

    return enabled && isTwelveDaysOfChristmas
}

const hasStandaloneFive = (content: string): boolean => /(^|[^\p{L}\p{N}.])5(?![\p{L}\p{N}.]|,\d)/u.test(content)

export function shouldPlayGoldRings(date: Date, enabled: boolean, content: string): boolean {
    return isGoldRingsActive(date, enabled) && hasStandaloneFive(content)
}

export function watchForGoldRingsContent(
    content: HTMLElement,
    enabled: boolean,
    isCurrentNavigation: () => boolean,
    onMatch: () => void
): () => void {
    const shouldStopWatching = (): boolean => {
        if (!isCurrentNavigation() || !isGoldRingsActive(new Date(), enabled)) {
            return true
        }
        if (!hasStandaloneFive(content.innerText)) {
            return false
        }

        onMatch()
        return true
    }

    if (shouldStopWatching()) {
        return () => undefined
    }

    const observer = new MutationObserver(() => {
        if (shouldStopWatching()) {
            observer.disconnect()
        }
    })
    observer.observe(content, { childList: true, characterData: true, subtree: true })

    return () => observer.disconnect()
}

export function playGoldRings(): void {
    goldRingsAudio ??= new Audio('/static/sounds/five-gold-rings.mp3')
    goldRingsAudio.pause()
    goldRingsAudio.currentTime = 0
    goldRingsAudio.volume = 0.5
    void goldRingsAudio.play().catch(() => undefined)
}
