import { contrastRatio } from 'lib/utils/colors'

import { siteTheme } from './siteTheme'

const READ_STYLE = {
    background_color: '#fdf6e3',
    text_color: '#2a2633',
    button_color: '#7b3fe4',
    button_text_color: '#ffffff',
    button_border_radius: 6,
}
const NO_BUTTON = { button_color: null, button_text_color: null, button_border_radius: null }

describe('siteTheme', () => {
    it('uses the site colors when they are readable', () => {
        expect(siteTheme(READ_STYLE).appearance).toEqual({
            backgroundColor: '#fdf6e3',
            textColor: '#2a2633',
            borderColor: '#ddd7c9',
            submitButtonColor: '#7b3fe4',
            submitButtonTextColor: '#ffffff',
            ratingButtonColor: '#f0ead8',
            ratingButtonActiveColor: '#7b3fe4',
            inputBackground: '#fdf6e3',
            fontFamily: 'inherit',
            borderRadius: '6px',
        })
    })

    it.each([
        ['faint text on a light page', { ...READ_STYLE, text_color: '#d8d2c0' }, 'textColor', '#000000'],
        [
            'faint text on a dark page',
            { ...READ_STYLE, background_color: '#14121a', text_color: '#2a2633' },
            'textColor',
            '#ffffff',
        ],
        [
            'a button that blends into the page',
            { ...READ_STYLE, button_color: '#f6efdc' },
            'submitButtonColor',
            '#2a2633',
        ],
        ['unreadable button text', { ...READ_STYLE, button_text_color: '#8a5af0' }, 'submitButtonTextColor', '#ffffff'],
        ['no button on the page', { ...READ_STYLE, ...NO_BUTTON }, 'submitButtonColor', '#2a2633'],
        ['a pill-shaped button', { ...READ_STYLE, button_border_radius: 9999 }, 'borderRadius', '16px'],
        ['no button radius to copy', { ...READ_STYLE, ...NO_BUTTON }, 'borderRadius', undefined],
    ])('corrects %s', (_name, style, field, expected) => {
        expect(siteTheme(style).appearance[field as keyof ReturnType<typeof siteTheme>['appearance']]).toBe(expected)
    })

    it.each([
        ['light page', READ_STYLE],
        ['dark page with dim text', { ...READ_STYLE, background_color: '#101014', text_color: '#3a3a40' }],
        ['button the color of the page', { ...READ_STYLE, button_color: '#fdf6e3', button_text_color: '#fdf6e3' }],
    ])('keeps text readable on a %s', (_name, style) => {
        const { appearance } = siteTheme(style)

        expect(contrastRatio(appearance.textColor!, appearance.backgroundColor!)).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(appearance.submitButtonTextColor!, appearance.submitButtonColor!)).toBeGreaterThanOrEqual(
            4.5
        )
    })
})
