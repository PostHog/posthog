import type { Navigation3000Mode } from './navigationLogic'

/** The page layout. Splits `Navigation3000Mode`'s `full` into classic and the two Today forms. */
export type LayoutMode = 'bare' | 'minimal' | 'embedded' | 'classic' | 'today-framed' | 'today-phone'

export function resolveLayoutMode({
    mode,
    todayRail,
    phoneLayout,
}: {
    mode: Navigation3000Mode
    todayRail: boolean
    phoneLayout: boolean
}): LayoutMode {
    switch (mode) {
        case 'none':
            return 'bare'
        case 'minimal':
            return 'minimal'
        case 'embedded':
            return 'embedded'
        case 'full':
            if (!todayRail) {
                return 'classic'
            }
            return phoneLayout ? 'today-phone' : 'today-framed'
    }
}
