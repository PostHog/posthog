import React, { useState } from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'

import { isMobile, Loading } from 'lib/utils'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

import { Tabs, Row, Col, Card, Button, Tooltip } from 'antd'
import { FUNNEL_VIZ, ACTIONS_TABLE, ACTIONS_BAR_CHART_VALUE } from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionContainer } from 'scenes/retention/RetentionContainer'

import { Paths } from 'scenes/paths/Paths'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic, logicFromInsight, ViewType } from './insightLogic'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { SavedFunnels } from './SavedCard'
import { ReloadOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'

import './Insights.scss'
import { ErrorMessage, TimeOut } from './EmptyStates'
import { People } from 'scenes/funnels/People'
import { InsightsTable } from './InsightsTable'
import { TrendInsight } from 'scenes/trends/Trends'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { HotKeys } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightDisplayConfig } from './InsightTabs/InsightDisplayConfig'
import { PageHeader } from 'lib/components/PageHeader'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'

export interface BaseTabProps {
    annotationsToCreate: any[] // TODO: Type properly
}

dayjs.extend(relativeTime)
const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function Insights(): JSX.Element {
    return (
        <div className="insights-page">
            <PageHeader title="Insights" />
        </div>
    )
}

function FunnelInsight(): JSX.Element {
    const { stepsWithCount, isValidFunnel, stepsWithCountLoading } = useValues(funnelLogic({}))

    return (
        <div style={{ height: 300, position: 'relative' }}>
            {stepsWithCountLoading && <Loading />}
            {isValidFunnel ? (
                <FunnelViz steps={stepsWithCount} />
            ) : (
                !stepsWithCountLoading && (
                    <div
                        style={{
                            textAlign: 'center',
                        }}
                    >
                        <span>
                            Enter the details to your funnel and click 'calculate' to create a funnel visualization
                        </span>
                    </div>
                )
            )}
        </div>
    )
}

function FunnelPeople(): JSX.Element {
    const { stepsWithCount } = useValues(funnelLogic())
    if (stepsWithCount && stepsWithCount.length > 0) {
        return <People />
    }
    return <></>
}
