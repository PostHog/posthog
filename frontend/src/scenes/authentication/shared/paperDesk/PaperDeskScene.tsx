import './PaperDesk.scss'

import { type ReactNode, useEffect, useState } from 'react'

import { Logo } from 'lib/brand/Logo'

/** Types the two mono corner notes (// ...), honoring reduced-motion. Presentational only. */
function Typewriter({ lines }: { lines: string[] }): JSX.Element {
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
        <div className="PaperDesk__notes" aria-hidden>
            {parts.map((part, idx) => (
                <div key={idx} className="PaperDesk__notes-line">
                    {part}
                    {idx === parts.length - 1 && <span className="PaperDesk__caret" />}
                </div>
            ))}
        </div>
    )
}

/** Full-viewport paper-desk stage: dotted parchment + accent glow + mono corner notes + docs link. */
export function PaperDeskScene({ notes, children }: { notes: string[]; children: ReactNode }): JSX.Element {
    return (
        <div className="PaperDesk">
            <Typewriter lines={notes} />
            <div className="PaperDesk__content">
                <div className="PaperDesk__column">{children}</div>
            </div>
        </div>
    )
}

/** Logo (or custom header) + white card + optional footer note — the column contents. */
export function PaperDeskCard({
    top,
    footer,
    children,
}: {
    top?: ReactNode
    footer?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <>
            {top === undefined ? (
                <span className="PaperDesk__logo">
                    <Logo />
                </span>
            ) : (
                top
            )}
            <div className="PaperDesk__card">{children}</div>
            {footer}
        </>
    )
}
