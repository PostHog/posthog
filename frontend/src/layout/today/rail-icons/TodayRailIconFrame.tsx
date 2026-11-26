import './TodayRailIcon.scss'

import { ReactNode, useId } from 'react'

export type TodayRailIconName =
    | 'home'
    | 'chats'
    | 'analytics'
    | 'monitor'
    | 'people'
    | 'release'
    | 'automate'
    | 'data'
    | 'products'

interface TodayRailIconFrameProps {
    name: TodayRailIconName
    mask?: ReactNode
    line: (maskUrl: string) => ReactNode
    fill?: (maskUrl: string) => ReactNode
}

/** Ancestors opt in with `data-today-rail-active` (shows the fill) and `data-today-rail-hover` (plays the motion). */
export function TodayRailIconFrame({ name, mask, line, fill = line }: TodayRailIconFrameProps): JSX.Element {
    // Colons in React ids break the `url(#id)` reference.
    const maskId = `today-rail-icon-${useId().replace(/:/g, '')}`
    const maskUrl = `url(#${maskId})`
    return (
        <svg
            className={`TodayRailIcon TodayRailIcon--${name}`}
            viewBox="0 0 24 24"
            aria-hidden
            focusable="false"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            {mask && (
                <defs>
                    <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
                        <g stroke="none">
                            <rect width="24" height="24" fill="#fff" />
                            {mask}
                        </g>
                    </mask>
                </defs>
            )}
            <g className="TodayRailIcon__line" fill="none">
                {line(maskUrl)}
            </g>
            <g className="TodayRailIcon__fill" fill="currentColor">
                {fill(maskUrl)}
            </g>
        </svg>
    )
}
