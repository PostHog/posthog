import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ChangeEvent } from 'react'

import { Input } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPane } from './TodayPane'
import { TodayPaneGroup } from './TodayPaneGroup'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneState } from './TodayPaneState'
import { todayToolsLogic, toolLabel } from './todayToolsLogic'

export function TodayToolsSidebar(): JSX.Element {
    const { toolGroups, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { location } = useValues(router)

    return (
        <TodayPane
            label="Tools"
            header={
                <Input
                    type="search"
                    placeholder="Search tools"
                    aria-label="Search tools"
                    value={search}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                    data-attr="today-tools-search"
                />
            }
        >
            {!toolGroups.length ? (
                <TodayPaneState message="No tools match that search." />
            ) : (
                toolGroups.map((group) => (
                    <TodayPaneGroup key={group.category} label={group.category}>
                        {group.tools.map((tool) => {
                            const href = tool.href ?? ''
                            return (
                                <TodayPaneRow
                                    key={href}
                                    label={toolLabel(tool)}
                                    icon={iconForType(
                                        (tool.iconType ?? tool.type) as FileSystemIconType,
                                        tool.iconColor
                                    )}
                                    to={href}
                                    active={!!href && location.pathname.endsWith(href.split('?')[0])}
                                    dataAttr="today-tool"
                                />
                            )
                        })}
                    </TodayPaneGroup>
                ))
            )}
        </TodayPane>
    )
}
