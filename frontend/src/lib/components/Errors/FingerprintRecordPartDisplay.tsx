import { Tooltip } from '@posthog/lemon-ui'
import useIsHovering from 'lib/hooks/useIsHovering'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'

import { FingerprintRecordPart } from './stackFrameLogic'

export function FingerprintRecordPartDisplay({
    part,
    className,
}: {
    part: FingerprintRecordPart
    className?: string
}): JSX.Element {
    const iconRef = useRef<HTMLDivElement>(null)
    const isHovering = useIsHovering(iconRef)
    return (
        <Tooltip title={getPartPieces(part)} placement="right">
            <span ref={iconRef}>
                <IconFingerprint className={className} color={isHovering ? 'red' : 'gray'} fontSize="17px" />
            </span>
        </Tooltip>
    )
}

function getPartPieces(component: FingerprintRecordPart): React.ReactNode {
    if (component.type === 'manual') {
        return null
    }
    const pieces = component.pieces || []
    return (
        <div className="text-[0.70rem] leading-[0.85rem]">
            <span>Fingerprinted by</span>
            <ul>
                {pieces.map((piece, index) => (
                    <li key={index} className={cn('list-disc ml-4')}>
                        {piece}
                    </li>
                ))}
            </ul>
        </div>
    )
}
