let goldRingsAudio: HTMLAudioElement | null = null

export function shouldPlayGoldRings(date: Date, enabled: boolean, content: string): boolean {
    const month = date.getMonth()
    const day = date.getDate()
    const isTwelveDaysOfChristmas = (month === 11 && day >= 25) || (month === 0 && day <= 5)

    return enabled && isTwelveDaysOfChristmas && /(^|\D)5(?!\d)/.test(content)
}

export function playGoldRings(): void {
    goldRingsAudio ??= new Audio('/sounds/five-gold-rings.mp3')
    goldRingsAudio.pause()
    goldRingsAudio.currentTime = 0
    goldRingsAudio.volume = 0.5
    void goldRingsAudio.play().catch(() => undefined)
}
