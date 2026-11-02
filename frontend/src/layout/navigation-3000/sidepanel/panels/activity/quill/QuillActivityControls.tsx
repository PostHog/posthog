import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'

import {
    ActivityFilters,
    sidePanelActivityLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { todayContextPanelLogic } from '~/layout/today/todayContextPanelLogic'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { QuillActivityMemberFilter } from './QuillActivityMemberFilter'
import { QuillActivitySubscribeMenu } from './QuillActivitySubscribeMenu'

export function QuillActivityControls({ contextFromPage }: { contextFromPage: ActivityFilters }): JSX.Element {
    const { activeFilters } = useValues(sidePanelActivityLogic)
    const { setActiveFilters } = useActions(sidePanelActivityLogic)
    const { close } = useActions(todayContextPanelLogic)
    const hasItemContext = Boolean(contextFromPage.item_id)

    return (
        <div className="flex items-center justify-between gap-2">
            <Text size="xs" variant="muted" render={<span className="m-0 min-w-0" />}>
                Activity on{' '}
                <span className="font-semibold text-foreground">
                    {hasItemContext
                        ? `this ${humanizeScope(contextFromPage.scope!, true).toLowerCase()}`
                        : `all ${humanizeScope(contextFromPage.scope!).toLowerCase()}`}
                </span>
            </Text>
            <div className="flex min-w-0 items-center gap-1">
                <QuillActivitySubscribeMenu
                    properties={[
                        {
                            key: 'scope',
                            type: PropertyFilterType.Event,
                            value: contextFromPage.scope!,
                            operator: PropertyOperator.Exact,
                        },
                        ...(hasItemContext
                            ? [
                                  {
                                      key: 'item_id',
                                      type: PropertyFilterType.Event as const,
                                      value: contextFromPage.item_id,
                                      operator: PropertyOperator.Exact,
                                  },
                              ]
                            : []),
                    ]}
                    onNavigate={close}
                />
                <QuillActivityMemberFilter
                    value={activeFilters?.user ?? null}
                    onChange={(user) => setActiveFilters({ ...activeFilters, user: user?.id ?? undefined })}
                />
            </div>
        </div>
    )
}
