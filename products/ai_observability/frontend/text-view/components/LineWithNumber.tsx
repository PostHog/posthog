import { useEffect, useRef } from 'react'

interface LineWithNumberProps {
    lineNumber: number
    content: string
    isActive: boolean
    padding: number
}

export function LineWithNumber({ lineNumber, content, isActive, padding }: LineWithNumberProps): JSX.Element {
    const lineRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (isActive && lineRef.current) {
            lineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            lineRef.current.classList.add('bg-warning-highlight', 'border-l-4', 'border-warning')
            const timer = setTimeout(() => {
                lineRef.current?.classList.remove('bg-warning-highlight', 'border-l-4', 'border-warning')
            }, 3000)
            return () => clearTimeout(timer)
        }
    }, [isActive])

    const paddedLineNumber = padding > 0 ? lineNumber.toString().padStart(padding, '0') : lineNumber.toString()

    return (
        <span ref={lineRef}>
            <span className="text-muted">L{paddedLineNumber}:</span>
            {content}
        </span>
    )
}
