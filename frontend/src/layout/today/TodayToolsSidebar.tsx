import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { toolHrefForPath, toolLabel } from 'scenes/tools/toolsUtils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { todayToolsLogic } from './todayToolsLogic'

export function TodayToolsSidebar(): JSX.Element {
    const { tools, toolGroups, recentTools, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { location } = useValues(router)
    const activeHref = toolHrefForPath(removeProjectIdIfPresent(location.pathname), tools)
    const groups = [
        ...(recentTools.length ? [{ key: 'recent', label: 'Recently viewed', tools: recentTools }] : []),
        ...toolGroups.map((group) => ({ key: group.category, label: group.category, tools: group.tools })),
    ]
    // A tool can show in Recently viewed and in its own group, so the group keeps the two rows apart on the keyboard path.
    const optionValue = (groupKey: string, tool: FileSystemImport): string => `${groupKey}:${tool.href ?? ''}`

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search tools"
                dataAttr="today-tools-search"
            >
                {!groups.length ? (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        No tools match that search.
                    </Text>
                ) : (
                    groups.map((group, index) => (
                        <div key={group.key}>
                            <TodayPaneGroupLabel first={index === 0}>{group.label}</TodayPaneGroupLabel>
                            {group.tools.map((tool) => {
                                const href = tool.href ?? ''
                                return (
                                    <TodayPaneRow
                                        key={href}
                                        value={optionValue(group.key, tool)}
                                        label={toolLabel(tool)}
                                        icon={iconForType(
                                            (tool.iconType ?? tool.type) as FileSystemIconType,
                                            tool.iconColor
                                        )}
                                        to={href}
                                        active={!!href && href === activeHref}
                                        dataAttr={group.key === 'recent' ? 'today-tool-recent' : 'today-tool'}
                                    />
                                )
                            })}
                        </div>
                    ))
                )}
            </TodayPaneSearchList>
        </div>
    )
}
