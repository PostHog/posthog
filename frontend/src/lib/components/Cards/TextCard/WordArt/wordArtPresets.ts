interface WordArtPreset {
    id: string
    label: string
}

export const WORD_ART_PRESETS: WordArtPreset[] = [
    { id: 'rainbow', label: 'Rainbow' },
    { id: 'sunset', label: 'Sunset' },
    { id: 'chrome', label: 'Chrome' },
    { id: 'neon', label: 'Neon sign' },
    { id: 'outline', label: 'Outline' },
    { id: 'extrude', label: '3D blocks' },
    { id: 'shadow', label: 'Hard shadow' },
    { id: 'fire', label: 'Fire' },
    { id: 'ice', label: 'Ice' },
    { id: 'stripes', label: 'Retro stripes' },
    { id: 'arch', label: 'Arch' },
]

export const DEFAULT_WORD_ART_STYLE = 'rainbow'

export function normalizeWordArtStyle(value: string | null | undefined): string {
    return WORD_ART_PRESETS.some((preset) => preset.id === value) ? (value as string) : DEFAULT_WORD_ART_STYLE
}

export type WordArtSize = 'small' | 'medium' | 'large'

export const WORD_ART_SIZES: WordArtSize[] = ['small', 'medium', 'large']

export const DEFAULT_WORD_ART_SIZE: WordArtSize = 'medium'

export function normalizeWordArtSize(value: string | null | undefined): WordArtSize {
    return WORD_ART_SIZES.includes(value as WordArtSize) ? (value as WordArtSize) : DEFAULT_WORD_ART_SIZE
}
