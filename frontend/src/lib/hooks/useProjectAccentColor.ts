import { useValues } from 'kea'
import { useEffect } from 'react'

import { RGBToHSL, hexToRGB } from 'lib/utils/colors'

import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'

export const ACCENT_COLOR_HEX_PATTERN = /^#[0-9a-f]{6}$/i

/**
 * Applies the user's per-project accent color (see the UserUIConfiguration schema) by overriding
 * the brand color custom properties on the document root. Every accent-derived color (hover,
 * active, highlights, both themes) is computed from these HSL parts, so overriding the parts —
 * rather than each derived variable — recolors all of them at once.
 */
export function useProjectAccentColor(): void {
    const { projectAccentColor } = useValues(uiCustomizationLogic)

    useEffect(() => {
        const rootStyle = document.documentElement.style
        if (projectAccentColor && ACCENT_COLOR_HEX_PATTERN.test(projectAccentColor)) {
            const { r, g, b } = hexToRGB(projectAccentColor)
            const { h, s, l } = RGBToHSL(r, g, b)
            rootStyle.setProperty('--color-brand-primary-hue', String(h))
            rootStyle.setProperty('--color-brand-primary-saturation', `${s}%`)
            rootStyle.setProperty('--color-brand-primary-lightness', `${l}%`)
        } else {
            rootStyle.removeProperty('--color-brand-primary-hue')
            rootStyle.removeProperty('--color-brand-primary-saturation')
            rootStyle.removeProperty('--color-brand-primary-lightness')
        }
    }, [projectAccentColor])
}
