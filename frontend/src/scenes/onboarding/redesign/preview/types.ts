export interface MetricCard {
    label: string
    value: string
    delta?: string
    deltaPositive?: boolean
}

export interface ChartBlock {
    title: string
    /** 'trend' | 'bars' | 'table' */
    kind: 'trend' | 'bars' | 'table'
    /** Only for kind='table' */
    rows?: { label: string; value: string }[]
}

export interface HomeListItem {
    label: string
    iconKey?: string
}

export interface PreviewEvent {
    name: string
    /** Person identifier shown in the right column (an email, or an anonymous distinct id). */
    person: string
    /** Single-letter avatar initial. */
    initial: string
    /** Tailwind background-color class for the avatar chip. */
    color: string
    /** Recognized PostHog/core event (Pageview, Exception, …) — renders the colorful PostHog icon. */
    recognized?: boolean
    /** Person is an anonymous distinct id rather than an identified email. */
    anon?: boolean
    /** URL / SCREEN column value; omitted events render a dash. */
    url?: string
}

export type PreviewPage =
    | { kind: 'empty'; title?: string; subtitle?: string }
    | { kind: 'dashboard'; metrics: MetricCard[]; charts?: ChartBlock[] }
    | { kind: 'insight'; title?: string; subtitle?: string }
    | { kind: 'activity'; events: PreviewEvent[] }
    | {
          kind: 'home'
          greetingName: string
          pinnedDashboards: HomeListItem[]
          recents: HomeListItem[]
          starred: HomeListItem[]
      }

export interface SidebarItem {
    label: string
    iconKey?: string
    active?: boolean
    /** If true, renders a chevron to indicate it opens a panel */
    expandable?: boolean
}

export interface SidebarSection {
    title?: string
    items: SidebarItem[]
}

export interface SidebarFooterItem {
    label: string
    iconKey?: string
}

export interface SidebarConfig {
    sections: SidebarSection[]
    footerItems: SidebarFooterItem[]
}

export interface PreviewConfig {
    org: { name: string; logoUrl?: string | null }
    sidebar: SidebarConfig
    page: PreviewPage
    rightPanel?: { title: string; visible?: boolean } | null
}
