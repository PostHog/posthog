let goldRingsAudio: HTMLAudioElement | null = null
const optOutKey = 'christmas-gold-rings-muted'
const optOutPhrase = 'ihatexmas'
const sequenceTimeoutMs = 2_000

const isPlainKey = (event: KeyboardEvent): boolean =>
    event.key.length === 1 && !event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey

export function isGoldRingsMuted(): boolean {
    return sessionStorage.getItem(optOutKey) === 'true'
}

export function listenForGoldRingsOptOut(isEnabled: () => boolean): () => void {
    let progress = 0
    let lastKeyAt = 0

    const onKeyDown = (event: KeyboardEvent): void => {
        if (!isEnabled() || isGoldRingsMuted() || !isPlainKey(event)) {
            return
        }
        if (event.target instanceof HTMLInputElement && event.target.type === 'password') {
            return
        }
        if (event.key === ' ') {
            return
        }

        const now = Date.now()
        progress = now - lastKeyAt > sequenceTimeoutMs ? 0 : progress
        lastKeyAt = now
        const key = event.key.toLowerCase()
        progress = key === optOutPhrase[progress] ? progress + 1 : key === optOutPhrase[0] ? 1 : 0

        if (progress === optOutPhrase.length) {
            sessionStorage.setItem(optOutKey, 'true')
            goldRingsAudio?.pause()
            progress = 0
        }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
}

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
    getContent: () => HTMLElement | null,
    isEnabled: () => boolean,
    isCurrentNavigation: () => boolean,
    hasPlayed: () => boolean,
    onMatch: () => void
): () => void {
    const observationWindowMs = 10_000
    let contentObserver: MutationObserver | undefined
    let documentObserver: MutationObserver | undefined
    let scanFrame: number | undefined
    let isStopped = false
    const changedNodes = new Set<Node>()

    const stopWatching = (): void => {
        if (isStopped) {
            return
        }
        isStopped = true
        contentObserver?.disconnect()
        documentObserver?.disconnect()
        window.clearTimeout(timeout)
        if (scanFrame !== undefined) {
            window.cancelAnimationFrame(scanFrame)
        }
    }

    const checkForMatch = (text: string): void => {
        if (!isCurrentNavigation() || !isEnabled() || hasPlayed()) {
            stopWatching()
        } else if (shouldPlayGoldRings(new Date(), true, text)) {
            stopWatching()
            onMatch()
        }
    }

    const attachToContent = (): void => {
        if (isStopped) {
            return
        }
        if (!isCurrentNavigation() || !isEnabled() || hasPlayed()) {
            stopWatching()
            return
        }

        const content = getContent()
        if (!content) {
            return
        }

        documentObserver?.disconnect()
        documentObserver = undefined
        checkForMatch(content.innerText ?? content.textContent ?? '')
        if (isStopped) {
            return
        }

        contentObserver = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                if (mutation.type === 'characterData') {
                    changedNodes.add(mutation.target)
                } else {
                    mutation.addedNodes.forEach((node) => changedNodes.add(node))
                }
            }
            if (scanFrame === undefined) {
                scanFrame = window.requestAnimationFrame(() => {
                    scanFrame = undefined
                    const changedText = [...changedNodes]
                        .filter((node) => content.contains(node))
                        .map(
                            (node) =>
                                (node instanceof HTMLElement
                                    ? (node.innerText ?? node.textContent)
                                    : node.textContent) ?? ''
                        )
                        .join(' ')
                    changedNodes.clear()
                    if (changedText) {
                        checkForMatch(changedText)
                    } else if (!isCurrentNavigation() || !isEnabled() || hasPlayed()) {
                        stopWatching()
                    }
                })
            }
        })
        contentObserver.observe(content, { childList: true, characterData: true, subtree: true })
    }

    const timeout = window.setTimeout(stopWatching, observationWindowMs)
    attachToContent()
    if (!isStopped && !contentObserver) {
        documentObserver = new MutationObserver(attachToContent)
        if (document.documentElement) {
            documentObserver.observe(document.documentElement, { childList: true, subtree: true })
        }
    }

    return stopWatching
}

export function playGoldRings(): void {
    if (isGoldRingsMuted()) {
        return
    }
    goldRingsAudio ??= new Audio('/static/sounds/five-gold-rings.mp3')
    goldRingsAudio.pause()
    goldRingsAudio.currentTime = 0
    goldRingsAudio.volume = 0.5
    void goldRingsAudio.play().catch(() => undefined)
}
