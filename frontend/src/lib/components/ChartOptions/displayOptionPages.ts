import type { DisplayOptionGroupKey, DisplayOptionSection, DisplayOptionTab } from './displayOptions'

export interface DisplayOptionPage {
    key: string
    title: string
    count: number
    sections: DisplayOptionSection[]
}

export interface DisplayOptionPages {
    home: DisplayOptionSection[]
    pages: DisplayOptionPage[]
}

// Each axis is its own page; the line groups share one, like the "Lines" tab they replace.
const PAGE_OF_GROUP: Record<Exclude<DisplayOptionGroupKey, 'display'>, { key: string; title?: string }> = {
    'x-axis': { key: 'x-axis' },
    'y-axis': { key: 'y-axis' },
    'right-y-axis': { key: 'right-y-axis' },
    style: { key: 'lines', title: 'Lines' },
    overlays: { key: 'lines', title: 'Lines' },
}

const changedIn = (sections: DisplayOptionSection[]): number =>
    sections.reduce((sum, section) => sum + section.items.reduce((total, item) => total + item.changed, 0), 0)

// Splits the options into the ones shown straight away and pages one step away, for the quill panels.
export function displayOptionPages(tabs: DisplayOptionTab[]): DisplayOptionPages {
    const sections = tabs.flatMap((tab) => tab.sections)
    const home: DisplayOptionSection[] = []
    const more: DisplayOptionSection[] = []
    const pages: DisplayOptionPage[] = []

    for (const section of sections) {
        if (section.group === 'display') {
            const common = section.items.filter((item) => !item.advanced)
            const advanced = section.items.filter((item) => item.advanced)
            if (common.length > 0) {
                home.push({ ...section, items: common })
            }
            if (advanced.length > 0) {
                more.push({ ...section, items: advanced })
            }
            continue
        }
        const { key, title } = PAGE_OF_GROUP[section.group]
        const page = pages.find((existing) => existing.key === key)
        if (page) {
            page.sections.push(section)
        } else {
            pages.push({ key, title: title ?? section.title ?? key, count: 0, sections: [section] })
        }
    }

    if (more.length > 0) {
        pages.push({ key: 'more', title: 'More options', count: 0, sections: more })
    }

    return {
        home,
        pages: pages.map((page) => ({
            ...page,
            // The page header already names its axis.
            sections: page.sections.map((section) =>
                section.title === page.title ? { ...section, title: undefined } : section
            ),
            count: changedIn(page.sections),
        })),
    }
}
