import './Today.scss'

import type { ReactNode } from 'react'

import { IconStack, IconStackItem } from '@posthog/quill'

import type { TodayRowIcon } from './todayRowIcons'

export function TodayPromptItem({
    icon,
    title,
    meta,
    actions,
    dataAttr,
}: {
    icon: TodayRowIcon
    title: string
    meta: ReactNode
    actions?: ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <li className="TodayRow" data-attr={dataAttr}>
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <div className="min-w-0">
                <span className="TodayRow__title">{title}</span>
                <p className="TodayRow__meta">{meta}</p>
            </div>
            {actions ? <div className="TodayRow__end TodayPromptRow__actions">{actions}</div> : null}
        </li>
    )
}
