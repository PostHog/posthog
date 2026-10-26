import './TileDecorations.scss'

import * as hooligan from '@posthog/brand/hoggies/png/hooligan'

import { pngHoggie } from 'lib/brand/hoggies'

import type { TileBadge } from '~/types'

const CheekyHog = pngHoggie(hooligan)

interface TileDecorationsProps {
    badge?: TileBadge | null
    groupTitle?: string
}

export function TileDecorations({ badge, groupTitle }: TileDecorationsProps): JSX.Element | null {
    if (!badge && !groupTitle) {
        return null
    }
    return (
        <>
            {groupTitle && <div className="TileDecorations__group-title">{groupTitle}</div>}
            {badge === 'winner' && (
                <div className="TileDecorations__crown" role="img" aria-label="Winner">
                    {/* IconCrown is an outline with a cut-out, so this draws only its outer contour to get a solid crown. */}
                    <svg className="LemonIcon" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <path d="M12 3a.75.75 0 0 1 .628.34l3.86 5.903 5.384-3.14a.75.75 0 0 1 1.113.798l-2.399 11.7A1.75 1.75 0 0 1 18.872 20H5.128a1.75 1.75 0 0 1-1.714-1.399l-2.399-11.7a.75.75 0 0 1 1.113-.799l5.384 3.141 3.86-5.903A.75.75 0 0 1 12 3Z" />
                    </svg>
                </div>
            )}
            {badge === 'cheeky-hog' && (
                <div className="TileDecorations__hog" aria-hidden>
                    <CheekyHog className="w-12 h-12" />
                </div>
            )}
        </>
    )
}
