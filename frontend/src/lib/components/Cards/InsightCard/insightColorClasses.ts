import { InsightColor } from '~/types'

type InsightColorVariantClasses = {
    border?: string
    leftBorder?: string
    text?: string
    headerBg?: string
}

export const INSIGHT_COLOR_CLASSES: Partial<Record<InsightColor, InsightColorVariantClasses>> = {
    [InsightColor.Blue]: {
        border: 'border-[3px] border-[var(--blue)]',
        leftBorder: 'border-l-[4px] border-l-[var(--blue)] rounded-l-2xl',
        text: 'text-[var(--blue)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--blue)_10%,transparent)]',
    },
    [InsightColor.Purple]: {
        border: 'border-[3px] border-[var(--purple)]',
        leftBorder: 'border-l-[4px] border-l-[var(--purple)] rounded-l-2xl',
        text: 'text-[var(--purple)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--purple)_10%,transparent)]',
    },
    [InsightColor.Green]: {
        border: 'border-[3px] border-[var(--green)]',
        leftBorder: 'border-l-[4px] border-l-[var(--green)] rounded-l-2xl',
        text: 'text-[var(--green)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--green)_10%,transparent)]',
    },
    [InsightColor.Black]: {
        border: 'border-[3px] border-[var(--black)]',
        leftBorder: 'border-l-[4px] border-l-[var(--black)] rounded-l-2xl',
        text: 'text-[var(--black)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--black)_5%,transparent)]',
    },
    [InsightColor.Red]: {
        border: 'border-[3px] border-[var(--danger)]',
        leftBorder: 'border-l-[4px] border-l-[var(--danger)] rounded-l-2xl',
        text: 'text-[var(--danger)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--danger)_10%,transparent)]',
    },
    [InsightColor.Orange]: {
        border: 'border-[3px] border-[var(--warning)]',
        leftBorder: 'border-l-[4px] border-l-[var(--warning)] rounded-l-2xl',
        text: 'text-[var(--warning)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--warning)_10%,transparent)]',
    },
    [InsightColor.Teal]: {
        border: 'border-[3px] border-[var(--data-color-3)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-3)] rounded-l-2xl',
        text: 'text-[var(--data-color-3)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--data-color-3)_10%,transparent)]',
    },
    [InsightColor.Cyan]: {
        border: 'border-[3px] border-[var(--data-color-11)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-11)] rounded-l-2xl',
        text: 'text-[var(--data-color-11)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--data-color-11)_10%,transparent)]',
    },
    [InsightColor.Pink]: {
        border: 'border-[3px] border-[var(--data-color-9)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-9)] rounded-l-2xl',
        text: 'text-[var(--data-color-9)]',
        headerBg: 'bg-[color-mix(in_srgb,var(--data-color-9)_10%,transparent)]',
    },
}
