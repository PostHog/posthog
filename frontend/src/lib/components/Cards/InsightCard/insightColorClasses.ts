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
        headerBg: 'bg-[var(--blue)] bg-opacity-10',
    },
    [InsightColor.Purple]: {
        border: 'border-[3px] border-[var(--purple)]',
        leftBorder: 'border-l-[4px] border-l-[var(--purple)] rounded-l-2xl',
        text: 'text-[var(--purple)]',
        headerBg: 'bg-[var(--purple)] bg-opacity-10',
    },
    [InsightColor.Green]: {
        border: 'border-[3px] border-[var(--green)]',
        leftBorder: 'border-l-[4px] border-l-[var(--green)] rounded-l-2xl',
        text: 'text-[var(--green)]',
        headerBg: 'bg-[var(--green)] bg-opacity-10',
    },
    [InsightColor.Black]: {
        border: 'border-[3px] border-[var(--black)]',
        leftBorder: 'border-l-[4px] border-l-[var(--black)] rounded-l-2xl',
        text: 'text-[var(--black)]',
        headerBg: 'bg-[var(--black)] bg-opacity-5',
    },
    [InsightColor.Red]: {
        border: 'border-[3px] border-[var(--danger)]',
        leftBorder: 'border-l-[4px] border-l-[var(--danger)] rounded-l-2xl',
        text: 'text-[var(--danger)]',
        headerBg: 'bg-[var(--danger)] bg-opacity-10',
    },
    [InsightColor.Orange]: {
        border: 'border-[3px] border-[var(--warning)]',
        leftBorder: 'border-l-[4px] border-l-[var(--warning)] rounded-l-2xl',
        text: 'text-[var(--warning)]',
        headerBg: 'bg-[var(--warning)] bg-opacity-10',
    },
    [InsightColor.Teal]: {
        border: 'border-[3px] border-[var(--data-color-3)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-3)] rounded-l-2xl',
        text: 'text-[var(--data-color-3)]',
        headerBg: 'bg-[var(--data-color-3)] bg-opacity-10',
    },
    [InsightColor.Cyan]: {
        border: 'border-[3px] border-[var(--data-color-11)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-11)] rounded-l-2xl',
        text: 'text-[var(--data-color-11)]',
        headerBg: 'bg-[var(--data-color-11)] bg-opacity-10',
    },
    [InsightColor.Pink]: {
        border: 'border-[3px] border-[var(--data-color-9)]',
        leftBorder: 'border-l-[4px] border-l-[var(--data-color-9)] rounded-l-2xl',
        text: 'text-[var(--data-color-9)]',
        headerBg: 'bg-[var(--data-color-9)] bg-opacity-10',
    },
}
