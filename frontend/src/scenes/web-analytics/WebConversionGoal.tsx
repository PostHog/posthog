import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCursor } from '@posthog/icons'

import { CoreEventSelector } from 'lib/components/CoreEvents'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'
import { CoreEvent, NodeKind } from '~/queries/schema/schema-general'

import { ProductTab } from './common'

export interface WebConversionGoalProps {
    value?: { actionId: number } | { customEventName: string } | null
    onChange?: (value: { actionId: number } | { customEventName: string } | null) => void
}

export const WebConversionGoal = ({
    value: propsValue,
    onChange: propsOnChange,
}: WebConversionGoalProps = {}): JSX.Element | null => {
    const { isWindowLessThan } = useWindowSize()
    const { featureFlags } = useValues(featureFlagLogic)
    const { actions } = useValues(actionsModel)

    const {
        conversionGoal: logicConversionGoal,
        productTab,
        coreEvents,
        coreEventsLoaderLoading,
        availableCoreEventsForWebAnalytics,
    } = useValues(webAnalyticsLogic)
    const { setConversionGoal: logicSetConversionGoal } = useActions(webAnalyticsLogic)

    const conversionGoal = propsValue !== undefined ? propsValue : logicConversionGoal
    const setConversionGoal = propsOnChange ?? logicSetConversionGoal

    const [group, setGroup] = useState(TaxonomicFilterGroupType.CustomEvents)

    const coreEventsFeatureEnabled = !!featureFlags[FEATURE_FLAGS.NEW_TEAM_CORE_EVENTS]
    const conversionGoalsCoreEventsEnabled = !!featureFlags[FEATURE_FLAGS.CONVERSION_GOALS_CORE_EVENTS]
    const useCoreEventsSelector = coreEventsFeatureEnabled && conversionGoalsCoreEventsEnabled

    const placeholder = isWindowLessThan('xl')
        ? 'Goal'
        : isWindowLessThan('2xl')
          ? 'Conversion goal'
          : 'Add conversion goal'

    const taxonomicValue =
        conversionGoal && 'actionId' in conversionGoal ? conversionGoal.actionId : conversionGoal?.customEventName

    const selectedCoreEventId = useMemo(() => {
        if (!conversionGoal || coreEvents.length === 0) {
            return null
        }
        const matchingEvent = coreEvents.find((event) => {
            const filter = event.filter
            if ('actionId' in conversionGoal && filter.kind === NodeKind.ActionsNode) {
                return filter.id === conversionGoal.actionId
            }
            if ('customEventName' in conversionGoal && filter.kind === NodeKind.EventsNode) {
                return filter.event === conversionGoal.customEventName
            }
            return false
        })
        return matchingEvent?.id ?? null
    }, [conversionGoal, coreEvents])

    // Hide on non-Analytics tabs when not in controlled mode
    if (propsValue === undefined && productTab !== ProductTab.ANALYTICS) {
        return null
    }

    const handleTaxonomicChange = (changedValue: number | string | null, groupType: TaxonomicFilterGroupType): void => {
        if (groupType === TaxonomicFilterGroupType.Actions && typeof changedValue === 'number') {
            setConversionGoal({ actionId: changedValue })
            setGroup(TaxonomicFilterGroupType.Actions)
        } else if (
            groupType === TaxonomicFilterGroupType.CustomEvents &&
            typeof changedValue === 'string' &&
            changedValue
        ) {
            setConversionGoal({ customEventName: changedValue })
            setGroup(TaxonomicFilterGroupType.CustomEvents)
        } else {
            setConversionGoal(null)
        }
    }

    const handleCoreEventChange = (coreEvent: CoreEvent | null): void => {
        if (!coreEvent) {
            setConversionGoal(null)
            return
        }
        const filter = coreEvent.filter
        if (filter.kind === NodeKind.ActionsNode) {
            setConversionGoal({ actionId: filter.id })
        } else if (filter.kind === NodeKind.EventsNode && filter.event) {
            setConversionGoal({ customEventName: filter.event })
        }
    }

    const renderTaxonomicPopover = (): JSX.Element => (
        <TaxonomicPopover<number | string>
            allowClear
            data-attr="web-analytics-conversion-filter"
            groupType={group}
            value={taxonomicValue}
            onChange={handleTaxonomicChange}
            renderValue={() => {
                if (!conversionGoal) {
                    return null
                }
                if ('actionId' in conversionGoal) {
                    const action = actions.find((a) => a.id === conversionGoal.actionId)
                    return <span className="text-overflow max-w-full">{action?.name ?? 'Conversion goal'}</span>
                }
                return <span className="text-overflow max-w-full">{conversionGoal.customEventName}</span>
            }}
            groupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Actions]}
            icon={<IconCursor />}
            placeholder={placeholder}
            placeholderClass=""
            size="small"
        />
    )

    // Use TaxonomicPopover when feature flags are disabled
    if (!useCoreEventsSelector) {
        return renderTaxonomicPopover()
    }

    // Show loading state while core events are loading
    if (coreEventsLoaderLoading) {
        return (
            <CoreEventSelector
                coreEvents={[]}
                value={null}
                onChange={() => {}}
                placeholder={placeholder}
                size="small"
                loading={true}
                showDefineNewOption={false}
                data-attr="web-analytics-conversion-filter"
            />
        )
    }

    // Show TaxonomicPopover for legacy non-core-event goals so user can see/clear them
    if (conversionGoal && !selectedCoreEventId) {
        return renderTaxonomicPopover()
    }

    return (
        <CoreEventSelector
            coreEvents={availableCoreEventsForWebAnalytics}
            value={selectedCoreEventId}
            onChange={handleCoreEventChange}
            placeholder={placeholder}
            size="small"
            showDefineNewOption={true}
            data-attr="web-analytics-conversion-filter"
        />
    )
}
