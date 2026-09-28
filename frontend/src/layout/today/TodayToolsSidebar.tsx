import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonInput } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPaneRow } from './TodayPaneRow'
import { todayToolsLogic, toolLabel } from './todayToolsLogic'

export function TodayToolsSidebar(): JSX.Element {
    const { toolGroups, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { location } = useValues(router)

    return (
        <div className="TodayPane">
            <div className="TodayPane__filters">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search tools"
                    value={search}
                    onChange={setSearch}
                    data-attr="today-tools-search"
                    fullWidth
                />
            </div>
            <div className="TodayPane__scroll">
                {!toolGroups.length ? (
                    <div className="TodayPane__state">No tools match that search.</div>
                ) : (
                    toolGroups.map((group) => (
                        <div key={group.category}>
                            <div className="TodayPane__heading Today__label">{group.category}</div>
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
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
