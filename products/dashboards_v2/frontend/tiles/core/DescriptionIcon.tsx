import './DescriptionIcon.css'

import { IconInfo } from '@posthog/icons'

import { TapTooltip } from './TapTooltip'

export const DESCRIPTION_ICON_CLASS = 'dash-DescriptionIcon'
/** On a description's text that only an image or a printed page shows, because neither has a hover to open the icon. */
export const DESCRIPTION_IMAGE_ONLY_CLASS = 'dash-DescriptionIcon__image-text'

/** The info icon next to a tile's or a section's title, which opens the description. */
export function DescriptionIcon({ description }: { description: string }): JSX.Element {
    return (
        <TapTooltip
            text={description}
            className={`${DESCRIPTION_ICON_CLASS} inline-flex shrink-0 text-muted-foreground`}
        >
            <IconInfo />
        </TapTooltip>
    )
}
