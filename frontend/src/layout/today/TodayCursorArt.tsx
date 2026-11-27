import type { TodayCursorRefs } from './todayCursorDriver'

// The cursor art's own colors, not theme tokens: it is an illustration and looks the same in both themes.
const CURSOR_INK = '#6b44bc'
const CURSOR_PAPER = '#f8f7f2'

/** The pretend cursor's arrow and click ripple. `todayCursorRun` moves and presses it. */
export function TodayCursorArt({ refs }: { refs: TodayCursorRefs }): JSX.Element {
    return (
        <div ref={refs.x} aria-hidden className="pointer-events-none fixed top-0 left-0 z-[var(--z-tooltip)]">
            <div ref={refs.y}>
                <div
                    ref={refs.ripple}
                    className="absolute top-0 left-0 size-12 rounded-full opacity-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: CURSOR_INK }}
                />
                <div ref={refs.press} className="origin-top-left">
                    {/* The arrow's tip is the click point, at the origin. The solid copy behind it gives it depth. */}
                    <svg
                        viewBox="-4 -1.5 22 20"
                        width="28"
                        height="25"
                        className="absolute top-[-2px] left-[-5px] drop-shadow-sm"
                    >
                        <path
                            d="M-3 1.5 L11 6 L6.8 8.5 L13 14.7 L10.2 17.5 L4 11.3 L1.5 15.5 Z"
                            fill={CURSOR_INK}
                            stroke={CURSOR_INK}
                            strokeWidth="1.4"
                            strokeLinejoin="round"
                        />
                        <path
                            d="M0 0 L14 4.5 L9.8 7 L16 13.2 L13.2 16 L7 9.8 L4.5 14 Z"
                            fill={CURSOR_PAPER}
                            stroke={CURSOR_INK}
                            strokeWidth="1.4"
                            strokeLinejoin="round"
                        />
                    </svg>
                </div>
            </div>
        </div>
    )
}
