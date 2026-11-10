import './Today.scss'

import { IconStack, IconStackItem } from '@posthog/quill'

import { WATCHED_PRODUCT_ICONS } from './todayRowIcons'

export function TodayWatchedNote({ text }: { text: string }): JSX.Element {
    return (
        <p className="TodayWatchedNote">
            <IconStack className="TodayWatchedNote__icons" aria-hidden>
                {WATCHED_PRODUCT_ICONS.map((icon, index) => (
                    <IconStackItem key={index} color={icon.color}>
                        {icon.glyph}
                    </IconStackItem>
                ))}
            </IconStack>
            <span>{text}</span>
        </p>
    )
}
