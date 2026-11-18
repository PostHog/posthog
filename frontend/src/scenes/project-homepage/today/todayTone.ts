import { useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export type TodayTone = 'risk' | 'good' | 'neutral'

interface TodayTonePalette {
    risk: string
    good: string
    neutral: string
    line: string
}

const PALETTE: Record<'light' | 'dark', TodayTonePalette> = {
    light: { risk: '#d6453a', good: '#1f9d55', neutral: '#55554f', line: '#c4c4bc' },
    dark: { risk: '#ff7b6e', good: '#5fd38d', neutral: '#c9c9c2', line: '#55554f' },
}

export function useTodayTonePalette(): TodayTonePalette {
    const { isDarkModeOn } = useValues(themeLogic)
    return isDarkModeOn ? PALETTE.dark : PALETTE.light
}
