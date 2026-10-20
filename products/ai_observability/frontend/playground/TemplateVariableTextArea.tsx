import './TemplateVariableTextArea.scss'

import { useEffect, useLayoutEffect, useRef } from 'react'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { segmentTemplateText } from './playgroundTemplating'

/** A prompt editor that paints `{{variables}}` in place: accent when filled, warning when not.
 *
 * A textarea can't style its own contents, so the visible text is a backdrop div rendering the
 * same string; the textarea sits on top contributing the caret and selection over transparent
 * glyphs. `TemplateVariableTextArea.scss` holds every metric the two layers share, and explains
 * why. Tokens are recolored but never re-weighted: a weight change would alter glyph widths in
 * the proportional font and pull the caret away from the text.
 */
export function TemplateVariableTextArea({
    value,
    onChange,
    unfilledVariables,
    placeholder,
    minRows,
    onPressCmdEnter,
}: {
    value: string
    onChange: (value: string) => void
    unfilledVariables: string[]
    placeholder?: string
    minRows?: number
    onPressCmdEnter?: () => void
}): JSX.Element {
    const backdropRef = useRef<HTMLDivElement | null>(null)
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    // The field autosizes to its content, so it should never scroll; the sync is insurance
    // against rounding leaving the textarea a pixel scrollable.
    const syncScroll = (): void => {
        if (backdropRef.current && textAreaRef.current) {
            backdropRef.current.scrollTop = textAreaRef.current.scrollTop
            backdropRef.current.scrollLeft = textAreaRef.current.scrollLeft
        }
    }
    useLayoutEffect(syncScroll, [value])
    // `LemonTextArea` forwards only a few textarea attributes, and `onScroll` isn't among them,
    // so the listener goes on the element itself rather than widening the shared component.
    useEffect(() => {
        const element = textAreaRef.current
        element?.addEventListener('scroll', syncScroll)
        return () => element?.removeEventListener('scroll', syncScroll)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <div className="TemplateVariableTextArea w-full">
            <div ref={backdropRef} aria-hidden className="TemplateVariableTextArea__backdrop">
                {segmentTemplateText(value).map((segment, index) =>
                    segment.variableName === null ? (
                        <span key={index}>{segment.text}</span>
                    ) : (
                        <span
                            key={index}
                            className={
                                unfilledVariables.includes(segment.variableName)
                                    ? 'TemplateVariableTextArea__variable--unfilled'
                                    : 'TemplateVariableTextArea__variable'
                            }
                        >
                            {segment.text}
                        </span>
                    )
                )}
                {/* A trailing newline is collapsed when it ends the div's content, which would drop
                    the backdrop a line behind the textarea while typing at the end. */}
                {'\n'}
            </div>
            <LemonTextArea
                ref={textAreaRef}
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                minRows={minRows}
                onPressCmdEnter={onPressCmdEnter}
                className="TemplateVariableTextArea__field"
            />
        </div>
    )
}
