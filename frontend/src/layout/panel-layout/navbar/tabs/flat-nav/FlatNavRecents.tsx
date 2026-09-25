import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { NavLink } from '../../NavLink'
import { navRecentsLogic } from '../navRecentsLogic'
import { FlatNavSection } from './FlatNavSection'

function getItemName(item: FileSystemEntry): string {
    const lastPart = splitPath(item.path).pop()
    return unescapePath(lastPart ?? item.path)
}

export function FlatNavRecents(): JSX.Element {
    const { recentItems, recentItemsLoading, recentsCollapsed } = useValues(navRecentsLogic)
    const { setRecentsCollapsed } = useActions(navRecentsLogic)
    const recentItemsId = useId()
    const isSimpleSidepanelEnabled = useFeatureFlag('SIMPLE_SIDEPANEL')
    const { reportNavItemClicked } = useActions(eventUsageLogic)

    return (
        <FlatNavSection
            label="Recents"
            info="Items you viewed recently, most recent first."
            action={
                isSimpleSidepanelEnabled ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronDown className={recentsCollapsed ? 'rotate-180' : undefined} />}
                        onClick={() => setRecentsCollapsed(!recentsCollapsed)}
                        tooltip={recentsCollapsed ? 'Expand recents' : 'Collapse recents'}
                        aria-label={recentsCollapsed ? 'Expand recents' : 'Collapse recents'}
                        aria-expanded={!recentsCollapsed}
                        aria-controls={recentItemsId}
                        data-attr="nav-recents-toggle"
                    />
                ) : undefined
            }
        >
            <div id={recentItemsId} hidden={isSimpleSidepanelEnabled && recentsCollapsed}>
                <div className="flex flex-col gap-px group/colorful-product-icons colorful-product-icons-true">
                    {recentItemsLoading && recentItems.length === 0 ? (
                        <div className="flex items-center justify-center py-2">
                            <Spinner className="size-4" />
                        </div>
                    ) : recentItems.length === 0 ? (
                        <span className="text-xs text-tertiary px-2 py-1">No recent items</span>
                    ) : (
                        recentItems.map((item) => (
                            <NavLink
                                key={item.id}
                                to={item.href ?? ''}
                                label={getItemName(item)}
                                icon={iconForType(item.type as FileSystemIconType)}
                                isCollapsed={false}
                                data-attr={`nav-recent-item-${item.id}`}
                                onClick={() => reportNavItemClicked('recent', 'recents', item.type)}
                            />
                        ))
                    )}
                </div>
            </div>
        </FlatNavSection>
    )
}
