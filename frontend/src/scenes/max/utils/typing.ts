/**
 * Human-feeling delay (ms) before the next keystroke of the typewriter animation.
 *
 * Real typing isn't metronomic: it speeds up mid-word, slows at word boundaries, and pauses
 * noticeably after punctuation, with the occasional hesitation. `justTyped` is the character we
 * just committed; `nextChar` is what's coming, letting us keep letter runs quick.
 */
export function nextTypingDelayMs(justTyped: string, nextChar?: string): number {
    const rand = Math.random()
    let delay = 17 + rand * 23 // 17-40ms base keystroke

    if (/[.!?]/.test(justTyped)) {
        delay += 120 + Math.random() * 110 // full stop — noticeable pause
    } else if (/[,;:]/.test(justTyped)) {
        delay += 60 + Math.random() * 60 // clause break
    } else if (justTyped === ' ') {
        delay += 10 + Math.random() * 35 // between words
    } else if (rand < 0.05) {
        delay += 60 + Math.random() * 90 // occasional hesitation
    } else if (/[a-z]/i.test(justTyped) && nextChar && /[a-z]/i.test(nextChar)) {
        delay *= 0.8 // fast letter runs within a word
    }

    return delay
}
