import './PropertyIcons.scss'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { GatheredProperty } from './gatherIconProperties'

export interface PropertyIconsProps {
    recordingProperties: GatheredProperty[]
    loading?: boolean
    iconClassNames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({ recordingProperties, loading, iconClassNames }: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex gap-x-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                recordingProperties.map(({ property, value, label }) => (
                    <Tooltip key={property} title={label}>
                        <span className="flex items-center gap-x-0.5">
                            <PropertyIcon className={iconClassNames} property={property} value={value} />
                            <span className="SessionRecordingPreview__property-label text-secondary truncate">
                                {label}
                            </span>
                        </span>
                    </Tooltip>
                ))
            )}
        </div>
    )
}
