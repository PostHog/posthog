import { kea, path, selectors } from 'kea'
import { DataColorTheme, getColorVar } from 'lib/colors'

import type { dataThemeLogicType } from './dataThemeLogicType'

const POSTHOG_THEME: DataColorTheme = {
    'preset-1': getColorVar('data-color-1'),
    'preset-2': getColorVar('data-color-2'),
    'preset-3': getColorVar('data-color-3'),
    'preset-4': getColorVar('data-color-4'),
    'preset-5': getColorVar('data-color-5'),
    'preset-6': getColorVar('data-color-6'),
    'preset-7': getColorVar('data-color-7'),
    'preset-8': getColorVar('data-color-8'),
    'preset-9': getColorVar('data-color-9'),
    'preset-10': getColorVar('data-color-10'),
    'preset-11': getColorVar('data-color-11'),
    'preset-12': getColorVar('data-color-12'),
    'preset-13': getColorVar('data-color-13'),
    'preset-14': getColorVar('data-color-14'),
    'preset-15': getColorVar('data-color-15'),
}

const D3_SCHEME_CATEGORY_10: DataColorTheme = {
    'preset-1': '#1f77b4',
    'preset-2': '#ff7f0e',
    'preset-3': '#2ca02c',
    'preset-4': '#d62728',
    'preset-5': '#9467bd',
    'preset-6': '#8c564b',
    'preset-7': '#e377c2',
    'preset-8': '#7f7f7f',
    'preset-9': '#bcbd22',
    'preset-10': '#17becf',
}

export const dataThemeLogic = kea<dataThemeLogicType>([
    path(['scenes', 'dataThemeLogic']),
    selectors({
        themes: [
            () => [],
            () => ({
                posthog: POSTHOG_THEME,
                d3_category_10: D3_SCHEME_CATEGORY_10,
            }),
        ],
        getTheme: [
            (s) => [s.themes],
            (themes) =>
                (theme: string): DataColorTheme =>
                    themes[theme],
        ],
    }),
])
