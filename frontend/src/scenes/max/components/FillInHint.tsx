/**
 * Inline postfix cue for a fill-in suggestion. The suggestion's prefix has been typed into the
 * input as real text; this overlays an invisible mirror of that text (so the cue lands right after
 * it) followed by a wide blinking caret and a faded hint (e.g. "insert feature flag name").
 *
 * Rendered as an overlay positioned at the input's text origin; the parent hides the native caret
 * while it shows. `text` is the current input value (the typed prefix); `hint` is the postfix.
 */
export function FillInHint({ text, hint }: { text: string; hint: string }): JSX.Element {
    return (
        <span className="flex items-center text-sm whitespace-pre" data-attr="capability-fill-in-hint" aria-hidden>
            {/* Invisible copy of the typed text reserves its exact width so the caret sits after it. */}
            <span className="invisible">{text}</span>
            {/* Wide blinking caret (hogqlx-blink is the shared 1s blinking-cursor keyframe). */}
            <span className="hogqlx-blink ml-2 inline-block w-2 h-[1.15rem] rounded-[1px] bg-accent" />
            <span className="text-accent/60 ml-2 font-normal">{hint}</span>
        </span>
    )
}
