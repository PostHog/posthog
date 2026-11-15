import {
    IconCalendar,
    IconClock,
    IconCode,
    IconPuzzle,
    IconFilter,
    IconFunnels,
    IconGraph,
    IconInfo,
    IconLetter,
    IconLineGraph,
    IconList,
    IconLive,
    IconMinus,
    IconRefresh,
    IconRetention,
    IconTarget,
    IconTextWidth,
    IconTrending,
    IconTrends,
} from '@posthog/icons'

import { BLOCK_DEFINITIONS, BlockDefinition, BlockGroup, blockDefinition } from './blockLibrary/blockDefinitions'
import { componentLabel } from './blockLibrary/params'

export type LibraryIcon = typeof IconPuzzle

const ICONS: Record<string, LibraryIcon> = {
    Metric: IconTrending,
    Trend: IconLineGraph,
    TopList: IconList,
    Funnel: IconFunnels,
    SqlTable: IconCode,
    DateRange: IconCalendar,
    Interval: IconClock,
    PropertyFilter: IconFilter,
    Filters: IconFilter,
    Goal: IconTarget,
    RecentEvents: IconLive,
    Callout: IconInfo,
    Insight: IconGraph,
    Retention: IconRetention,
    Compare: IconTrends,
    Refresh: IconRefresh,
    Heading: IconLetter,
    Paragraph: IconTextWidth,
    Divider: IconMinus,
}

export const LIBRARY_GROUPS: BlockGroup[] = ['Data', 'Controls', 'Content']

export interface LibraryEntry extends BlockDefinition {
    icon: LibraryIcon
}

export const LIBRARY: LibraryEntry[] = BLOCK_DEFINITIONS.map((definition) => ({
    ...definition,
    icon: ICONS[definition.type] ?? IconPuzzle,
}))

const ELEMENT_LABELS: Record<string, string> = {
    h1: 'Heading',
    h2: 'Heading',
    h3: 'Heading',
    p: 'Text',
    hr: 'Divider',
    header: 'Header',
    main: 'Page',
    section: 'Section',
}

export function libraryLabel(blockType: string | null, tag?: string): string {
    if (blockType) {
        return blockDefinition(blockType)?.label ?? componentLabel(blockType)
    }
    return (tag && ELEMENT_LABELS[tag]) || 'Element'
}

export function libraryIcon(blockType: string | null): LibraryIcon {
    return (blockType && ICONS[blockType]) || IconPuzzle
}

/** The block type for analytics: a library block's type, never the name of a component the agent wrote. */
export function analyticsBlockType(blockType: string | null): string {
    if (!blockType) {
        return 'element'
    }
    return blockDefinition(blockType) ? blockType : 'custom'
}
