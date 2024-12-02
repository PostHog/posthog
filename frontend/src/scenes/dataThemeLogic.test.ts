import { DataColorThemeModel } from '~/types'

import { convertApiTheme } from './dataThemeLogic'

describe('convertApiTheme', () => {
    it('converts api theme', () => {
        const apiTheme: DataColorThemeModel = {
            id: 1,
            name: 'Default theme',
            colors: ['#ff0000', '#00ff00', '#0000ff'],
            is_global: true,
        }

        const theme = convertApiTheme(apiTheme)

        expect(theme).toEqual({
            'preset-1': '#ff0000',
            'preset-2': '#00ff00',
            'preset-3': '#0000ff',
        })
    })
})
