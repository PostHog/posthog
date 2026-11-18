import { contrastRatio, mixHexColors } from 'lib/utils/colors'
import { SurveyTheme } from 'scenes/surveys/constants'

import type { SiteStyleApi } from 'products/surveys/frontend/generated/api.schemas'

const WCAG_AA_TEXT_CONTRAST = 4.5
const WCAG_AA_NON_TEXT_CONTRAST = 3
const MAX_BORDER_RADIUS_PX = 16

function readableOn(background: string, preferred: string): string {
    if (contrastRatio(preferred, background) >= WCAG_AA_TEXT_CONTRAST) {
        return preferred
    }
    return contrastRatio('#000000', background) >= contrastRatio('#ffffff', background) ? '#000000' : '#ffffff'
}

export function siteTheme(style: SiteStyleApi): SurveyTheme {
    const background = style.background_color
    const text = readableOn(background, style.text_color)
    const button =
        style.button_color && contrastRatio(style.button_color, background) >= WCAG_AA_NON_TEXT_CONTRAST
            ? style.button_color
            : text
    const buttonText = readableOn(
        button,
        button === style.button_color ? (style.button_text_color ?? background) : background
    )

    return {
        id: 'site',
        name: 'Your site',
        description: 'Colors from your site',
        appearance: {
            backgroundColor: background,
            textColor: text,
            borderColor: mixHexColors(background, text, 0.15),
            submitButtonColor: button,
            submitButtonTextColor: buttonText,
            ratingButtonColor: mixHexColors(background, text, 0.06),
            ratingButtonActiveColor: button,
            inputBackground: background,
            fontFamily: 'inherit',
            ...(style.button_border_radius !== null && {
                borderRadius: `${Math.min(style.button_border_radius, MAX_BORDER_RADIUS_PX)}px`,
            }),
        },
    }
}
