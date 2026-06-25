import { useState, useEffect } from 'react'

/** Types the two mono corner notes (// ...), honoring reduced-motion. Presentational only. */
export function Typewriter({ lines }: { lines: string[] }): JSX.Element {
    const full = lines.join('\n')
    const reduce = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const [shown, setShown] = useState(reduce ? full.length : 0)

    useEffect(() => {
        if (reduce) {
            setShown(full.length)
            return
        }
        setShown(0)
        const schedule: number[] = []
        let acc = 350
        for (const ch of full) {
            acc += ch === '\n' ? 380 : 42
            schedule.push(acc)
        }
        const start = performance.now()
        // Elapsed-time driven so a throttled/background tab catches up in one tick.
        const id = setInterval(() => {
            const elapsed = performance.now() - start
            let k = 0
            while (k < schedule.length && schedule[k] <= elapsed) {
                k++
            }
            setShown(k)
            if (k >= schedule.length) {
                clearInterval(id)
            }
        }, 40)
        return () => clearInterval(id)
    }, [full, reduce])

    const parts = full.slice(0, shown).split('\n')
    return (
        <div
            className="absolute top-[clamp(20px,4vh,40px)] left-[clamp(20px,4vw,44px)] z-[2] min-h-[2.6em] font-mono text-xs leading-relaxed whitespace-pre"
            aria-hidden
        >
            {parts.map((part, idx) => (
                <div key={idx} className="text-primary/50 first:font-semibold">
                    {part}
                    {idx === parts.length - 1 && (
                        <span className="PaperDesk__caret inline-block w-2 h-[1.05em] ml-0.5 [vertical-align:-2px] bg-warning rounded-[1px]" />
                    )}
                </div>
            ))}
        </div>
    )
}
