import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconPencil, IconX } from '@posthog/icons'
import { LemonSelect, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'

import { customerJourneysLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/customerJourneysLogic'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../../types'
import { createPostHogWidgetNode } from '../NodeWrapper'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { getLogicKey } from '../utils'

type NotebookNodeCustomerJourneyAttributes = {
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
    tabId: string
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeCustomerJourneyAttributes>): JSX.Element | null => {
    const isJourneysEnabled = useFeatureFlag('CUSTOMER_ANALYTICS_JOURNEYS')
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const { setMenuItems, setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { personId, groupKey, groupTypeIndex, tabId } = attributes
    const logicKey = getLogicKey({ personId, groupKey, tabId })

    const logic = customerJourneysLogic({ key: logicKey, personId, groupKey, groupTypeIndex })
    useAttachedLogic(logic, notebookLogic)
    const { journeyOptions, journeysLoading, activeInsightLoading, filteredQuery, activeJourney } = useValues(logic)
    const { removeNode } = useActions(customerProfileLogic)

    useEffect(() => {
        if (activeJourney) {
            setTitlePlaceholder(`Customer journey - ${activeJourney.name}`)
        }
    }, [activeJourney?.name])

    useOnMountEffect(() => {
        setMenuItems([
            {
                label: 'Edit journeys',
                onClick: () => router.actions.push(urls.customerAnalyticsJourneys()),
                sideIcon: <IconPencil />,
            },
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.CustomerJourney),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

    if (journeysLoading || activeInsightLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    if (journeyOptions.length === 0) {
        return (
            <EmptyMessage
                title="No customer journeys configured"
                description="Add funnel insights as customer journeys to see how this customer moves through your product."
                buttonText="Configure journeys"
                buttonTo={urls.customerAnalyticsJourneys()}
            />
        )
    }

    if (!isJourneysEnabled || !expanded || !filteredQuery) {
        return null
    }

    return (
        <Query
            query={filteredQuery}
            attachTo={notebookLogic}
            readOnly
            context={{
                insightProps: {
                    dashboardItemId: `new-AdHoc.${logicKey}`,
                    query: filteredQuery,
                },
            }}
        />
    )
}

const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeCustomerJourneyAttributes>): JSX.Element => {
    const { personId, groupKey, groupTypeIndex, tabId } = attributes
    const logicKey = getLogicKey({ personId, groupKey, tabId })
    const logic = customerJourneysLogic({ key: logicKey, personId, groupKey, groupTypeIndex })
    const { journeyOptions, activeJourneyId } = useValues(logic)
    const { setActiveJourneyId } = useActions(logic)

    return (
        <div className="flex items-center gap-2 p-2">
            <LemonSelect value={activeJourneyId} onChange={setActiveJourneyId} options={journeyOptions} size="small" />
        </div>
    )
}

export const NotebookNodeCustomerJourney = createPostHogWidgetNode<NotebookNodeCustomerJourneyAttributes>({
    nodeType: NotebookNodeType.CustomerJourney,
    titlePlaceholder: 'Customer journey',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
        groupKey: {},
        groupTypeIndex: {},
        tabId: {},
    },
})
