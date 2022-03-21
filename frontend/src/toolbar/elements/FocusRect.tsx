import React from 'react'

// draw a beam around an element
export function FocusRect({ rect }: { rect: DOMRect }): JSX.Element {
    const widths = [0, rect.left + window.pageXOffset, rect.left + window.pageXOffset + rect.width, window.innerWidth]
    const heights = [
        0,
        rect.top + window.pageYOffset,
        rect.top + window.pageYOffset + rect.height,
        document.body.scrollHeight,
    ]

    const rects = []

    for (let i = 0; i < 3; i++) {
        for (let j = 0; j < 3; j++) {
            if (i !== 1 || j !== 1) {
                rects.push({
                    id: j * 3 + i,
                    x: widths[i],
                    w: widths[i + 1] - widths[i],
                    y: heights[j],
                    h: heights[j + 1] - heights[j],
                    bg:
                        i === 1 || j === 1
                            ? `linear-gradient(${
                                  j === 1 ? 180 : 90
                              }deg, rgba(0,0,0,0.1) calc(50% - 12px), rgba(255,255,255,0.1) calc(50% - 4px), rgba(255,255,255,0.1) calc(50% + 4px), rgba(0,0,0,0.1) calc(50% + 12px)`
                            : 'rgba(0,0,0,0.1)',
                })
            }
        }
    }

    return (
        <>
            {rects.map((r) => (
                <div
                    key={r.id}
                    style={{
                        position: 'absolute',
                        top: r.y,
                        left: r.x,
                        width: r.w,
                        height: r.h,
                        zIndex: 10,
                        background: r.bg,
                        backgroundBlendMode: 'multiply',
                        transition: 'opacity 0.3s',
                    }}
                />
            ))}
        </>
    )
}
