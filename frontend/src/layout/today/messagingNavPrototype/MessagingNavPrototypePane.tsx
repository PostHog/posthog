// PROTOTYPE, never merged: PostHog/michaelr-context#419. The Email & Messaging pane in the app sidebar (variants B and C).
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'

import { TodayPaneGroupLabel } from '../TodayPaneGroupLabel'
import { todayShellLogic } from '../todayShellLogic'
import { messagingNavPrototypeLogic } from './messagingNavPrototypeLogic'
import {
    MESSAGING_NAV_GROUPS,
    MESSAGING_SECTION_ICONS,
    MESSAGING_SECTION_LABELS,
    MESSAGING_SECTION_META,
    messagingSectionForPath,
    messagingSectionUrl,
} from './messagingNavPrototypeNav'

export function MessagingNavPrototypePane(): JSX.Element {
    const { location } = useValues(router)
    const { variant } = useValues(messagingNavPrototypeLogic)
    const { pickPane } = useActions(todayShellLogic)
    const [query, setQuery] = useState('')
    const activeSection = messagingSectionForPath(location.pathname)
    const search = query.trim().toLowerCase()

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={query}
                onQueryChange={setQuery}
                searchLabel="Search Email & Messaging"
                dataAttr="messaging-prototype-pane-search"
            >
                {variant === 'B' &&
                    !search && (
                        // B has no rail item, so the pane needs its own way back to where you came from.
                        <div className="flex flex-col gap-px pb-2">
                            <SidebarRow
                                value="back"
                                label="All products"
                                icon={<IconArrowLeft />}
                                to={urls.tools()}
                                onClick={() => pickPane('products')}
                                dataAttr="messaging-prototype-back"
                            />
                        </div>
                    )}
                {MESSAGING_NAV_GROUPS.map((group, index) => {
                    const sections = group.sections.filter((section) =>
                        MESSAGING_SECTION_LABELS[section].toLowerCase().includes(search)
                    )
                    if (sections.length === 0) {
                        return null
                    }
                    return (
                        <div key={index} className="flex flex-col gap-px pb-2">
                            {group.label ? (
                                <TodayPaneGroupLabel first={false}>{group.label}</TodayPaneGroupLabel>
                            ) : (
                                index > 0 && !search && <div className="mx-2 mb-2 border-t border-border" />
                            )}
                            {sections.map((section) => (
                                <SidebarRow
                                    key={section}
                                    value={section}
                                    label={MESSAGING_SECTION_LABELS[section]}
                                    meta={MESSAGING_SECTION_META[section]}
                                    icon={MESSAGING_SECTION_ICONS[section]}
                                    to={messagingSectionUrl(section)}
                                    active={activeSection === section}
                                    dataAttr={`messaging-prototype-row-${section}`}
                                />
                            ))}
                        </div>
                    )
                })}
            </SidebarSearchList>
        </div>
    )
}
