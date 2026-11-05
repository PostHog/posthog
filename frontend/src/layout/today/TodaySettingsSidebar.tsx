import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { MenuLabel, Tabs, TabsList, TabsTrigger, Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { settingsNavItems, settingsSectionLabel } from 'scenes/settings/settingsNavTree'
import { SettingsPaneLevel } from 'scenes/settings/settingsSectionScenes'
import { SettingLevelNames, SettingSection } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'

export function TodaySettingsSidebar(): JSX.Element {
    // The scene's own key, so a search here and the open section stay in step with the settings page.
    const logic = settingsLogic({ logicKey: 'settingsScene' })
    const { levels, filteredSections, collapsedGroups, navLevel, searchTerm, isSearching, searchResults } =
        useValues(logic)
    const { setSearchTerm, setNavLevel, toggleGroupCollapse } = useActions(logic)
    // Without an organization only the account level exists, so fall back to whichever level is there.
    const level = levels.includes(navLevel) ? navLevel : levels[0]
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)

    const renderSection = (section: SettingSection, destructive = false): JSX.Element => {
        const href = section.to ?? urls.settings(section.id)
        return (
            <TodayPaneRow
                key={section.id}
                value={`section:${section.id}`}
                label={settingsSectionLabel(section)}
                to={href}
                active={path === href || path.startsWith(`${href}/`)}
                variant={destructive ? 'destructive' : 'default'}
                // pinned: autocapture data-attr shared with the settings page nav
                dataAttr={`settings-menu-item-${section.id}`}
            />
        )
    }

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={searchTerm}
                onQueryChange={setSearchTerm}
                searchLabel="Search all settings"
                dataAttr="today-settings-search"
                listClassName="pb-24"
                header={
                    !isSearching &&
                    levels.length > 1 && (
                        <Tabs value={level} onValueChange={(next) => setNavLevel(next as SettingsPaneLevel)}>
                            <TabsList className="w-full">
                                {levels.map((id) => (
                                    <TabsTrigger
                                        key={id}
                                        value={id}
                                        className="flex-1"
                                        data-attr={`today-settings-tab-${id}`}
                                    >
                                        {SettingLevelNames[id]}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </Tabs>
                    )
                }
            >
                {isSearching ? (
                    searchResults.length === 0 ? (
                        <Text size="xs" variant="muted" className="block px-2 py-1">
                            No settings match that search.
                        </Text>
                    ) : (
                        searchResults.map((group, index) => (
                            <div key={group.sectionId}>
                                <TodayPaneGroupLabel first={index === 0}>
                                    {group.sectionTitle}
                                    <span className="ml-1 font-normal">({SettingLevelNames[group.level]})</span>
                                </TodayPaneGroupLabel>
                                {group.results.map((result) => (
                                    <TodayPaneRow
                                        key={result.settingId}
                                        value={`setting:${result.sectionId}:${result.settingId}`}
                                        label={result.settingTitle}
                                        to={urls.settings(result.sectionId, result.settingId)}
                                        // pinned: autocapture data-attr shared with the settings page search
                                        dataAttr={`settings-search-result-${result.settingId}`}
                                    />
                                ))}
                            </div>
                        ))
                    )
                ) : (
                    level &&
                    settingsNavItems(level, filteredSections).map((item) => {
                        if (item.kind === 'section') {
                            return renderSection(item.section, item.destructive)
                        }
                        const open = !collapsedGroups[item.key]
                        const Caret = open ? IconChevronDown : IconChevronRight
                        return (
                            <div key={item.key}>
                                <MenuLabel
                                    render={<button type="button" />}
                                    aria-expanded={open}
                                    data-attr="today-settings-group"
                                    onClick={() => toggleGroupCollapse(item.key)}
                                    className="mt-1 flex w-full cursor-pointer items-center gap-1 rounded-sm py-1 text-left font-normal text-foreground/70 hover:text-foreground"
                                >
                                    <span>{item.label}</span>
                                    <Caret className="size-3 shrink-0 opacity-60" />
                                </MenuLabel>
                                {open && (
                                    <div className="pl-2">{item.sections.map((section) => renderSection(section))}</div>
                                )}
                            </div>
                        )
                    })
                )}
            </TodayPaneSearchList>
        </div>
    )
}
