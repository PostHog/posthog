import './sparkline-loading.scss'

import colors from 'ansi-colors'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFilter, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSegmentedButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { LogMessage } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { AttributeBreakdowns } from './AttributeBreakdowns'
import { AttributesFilter } from './filters/AttributesFilter'
import { DateRangeFilter } from './filters/DateRangeFilter'
import { SearchTermFilter } from './filters/SearchTermFilter'
import { ServiceFilter } from './filters/ServiceFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    const { wrapBody, logs, sparkline, logsLoading, sparklineLoading } = useValues(logsLogic)
    const { runQuery } = useActions(logsLogic)

    useEffect(() => {
        runQuery()
    }, [runQuery])

    const labels: string[] = []
    let lastTime = ''
    let i = -1
    const timeseries = Object.entries(
        sparkline.reduce((accumulator, currentItem) => {
            if (currentItem.time !== lastTime) {
                labels.push(humanFriendlyDetailedTime(currentItem.time))
                lastTime = currentItem.time
                i++
            }
            const key = currentItem.level
            if (!accumulator[key]) {
                accumulator[key] = Array(sparkline.length)
            }
            accumulator[key][i] = currentItem.count
            return accumulator
        }, {})
    )
        .map(([level, data]) => ({
            name: level,
            values: data as number[],
            color: {
                fatal: 'danger-dark',
                error: 'danger',
                warn: 'warning',
                info: 'brand-blue',
                debug: 'muted',
                trace: 'muted-alt',
            }[level],
        }))
        .filter((series) => series.values.reduce((a, b) => a + b) > 0)

    return (
        <div className="flex flex-col gap-y-2 h-screen">
            <Filters />
            <>
                <div className={sparklineLoading ? 'sparkline-loading' : ''}>
                    <Sparkline labels={labels} data={timeseries} className="w-full" />
                    {sparklineLoading && <div className="sparkline-loading-overlay" />}
                </div>
                <DisplayOptions />
                <div className="flex-1">
                    <LemonTable
                        hideScrollbar
                        dataSource={logs}
                        loading={logsLoading}
                        size="small"
                        columns={[
                            {
                                title: 'Timestamp',
                                key: 'timestamp',
                                dataIndex: 'timestamp',
                                width: 0,
                                render: (timestamp) => <TZLabel time={(timestamp as string) + 'Z'} />,
                            },
                            {
                                title: 'Level',
                                key: 'severity_text',
                                dataIndex: 'severity_text',
                                width: 0,
                                render: (_, record) => <LogTag level={record.severity_text} />,
                            },
                            {
                                title: 'Message',
                                key: 'body',
                                dataIndex: 'body',
                                render: (body) => (
                                    <div className={cn(wrapBody ? '' : 'whitespace-nowrap')}>
                                        {colors.unstyle(body)}
                                    </div>
                                ),
                            },
                        ]}
                        expandable={{
                            noIndent: true,
                            expandedRowRender: (log) => <ExpandedLog log={log} />,
                        }}
                    />
                </div>
            </>
        </div>
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const { filterGroup, expandedAttributeBreaksdowns } = useValues(logsLogic)
    const { setFilterGroup, toggleAttributeBreakdown } = useActions(logsLogic)

    const attributes = log.attributes
    const rows = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    const addFilter = (key: string, value: string, operator = PropertyOperator.Exact): void => {
        const newGroup = { ...filterGroup.values[0] } as UniversalFiltersGroup

        newGroup.values.push({
            key,
            value: [value],
            operator: operator,
            type: PropertyFilterType.Log,
        })

        setFilterGroup({ ...filterGroup, values: [newGroup] }, false)
    }

    return (
        <LemonTable
            embedded
            showHeader={false}
            columns={[
                {
                    key: 'actions',
                    width: 0,
                    render: (_, record) => (
                        <div className="flex gap-x-0">
                            <LemonButton
                                tooltip="Add as filter"
                                size="xsmall"
                                onClick={() => addFilter(record.key, record.value)}
                            >
                                <IconPlusSquare />
                            </LemonButton>
                            <LemonButton
                                tooltip="Exclude as filter"
                                size="xsmall"
                                onClick={() => addFilter(record.key, record.value, PropertyOperator.IsNot)}
                            >
                                <IconMinusSquare />
                            </LemonButton>
                            <LemonButton
                                tooltip="Show breakdown"
                                size="xsmall"
                                onClick={() => toggleAttributeBreakdown(record.key)}
                            >
                                <IconFilter />
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
                    width: 0,
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                },
            ]}
            dataSource={rows}
            expandable={{
                noIndent: true,
                showRowExpansionToggle: false,
                isRowExpanded: (record) => expandedAttributeBreaksdowns.includes(record.key),
                expandedRowRender: (record) => <AttributeBreakdowns attribute={record.key} addFilter={addFilter} />,
            }}
        />
    )
}

const LogTag = ({ level }: { level: LogMessage['severity_text'] }): JSX.Element => {
    const type = (
        {
            debug: 'completion',
            info: 'caution',
            warn: 'warning',
            error: 'danger',
        } as Record<LogMessage['severity_text'], LemonTagType>
    )[level]

    return <LemonTag type={type}>{level}</LemonTag>
}

const Filters = (): JSX.Element => {
    const { logsLoading } = useValues(logsLogic)
    const { runQuery } = useActions(logsLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2 flex-wrap-reverse">
                <div className="flex gap-x-1 gap-y-2 flex-wrap">
                    <SeverityLevelsFilter />
                    <ServiceFilter />
                    <AttributesFilter />
                </div>
                <div className="flex gap-x-1">
                    <DateRangeFilter />
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={() => runQuery()}
                        loading={logsLoading}
                    >
                        {logsLoading ? 'Loading...' : 'Search'}
                    </LemonButton>
                </div>
            </div>
            <SearchTermFilter />
        </div>
    )
}

const DisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody } = useValues(logsLogic)
    const { setOrderBy, setWrapBody } = useActions(logsLogic)

    return (
        <div className="flex gap-x-2">
            <LemonSegmentedButton
                value={orderBy}
                onChange={setOrderBy}
                options={[
                    {
                        value: 'earliest',
                        label: 'Earliest',
                    },
                    {
                        value: 'latest',
                        label: 'Latest',
                    },
                ]}
                size="small"
            />
            <LemonCheckbox checked={wrapBody} bordered onChange={setWrapBody} label="Wrap message" size="small" />
        </div>
    )
}
