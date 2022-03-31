import { Button } from 'antd'
import React from 'react'
import { Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { InsightType } from '~/types'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { LemonButton } from 'lib/components/LemonButton'

const REFRESH_INTERVAL_MINUTES = 3

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)

    usePeriodicRerender(15000)

    return (
        <div className="text-muted-alt" style={{ height: 32, display: 'flex', alignItems: 'center' }}>
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            <span style={{ padding: '0 4px' }}>•</span>
            <Tooltip
                title={
                    <>
                        Insights can be refreshed
                        <br />
                        every {REFRESH_INTERVAL_MINUTES} minutes.
                    </>
                }
            >
                <Button
                    size="small"
                    type="link"
                    onClick={() => loadResults(true)}
                    disabled={
                        !!lastRefresh &&
                        dayjs()
                            .subtract(REFRESH_INTERVAL_MINUTES - 0.5, 'minutes')
                            .isBefore(lastRefresh)
                    }
                    style={{ padding: 0 }}
                >
                    <span style={{ fontSize: 14 }}>Refresh</span>
                </Button>
            </Tooltip>
            {<ViewSourceSql />}
        </div>
    )
}

export function ViewSourceSql(): JSX.Element {
    const { activeView, insight } = useValues(insightLogic)
    const { setActiveView, setFilters } = useActions(insightLogic)

    const onClickSource = (): void => {
        setFilters({
            insight: InsightType.USER_SQL,
            user_sql: insight.source_query,
        })
        setActiveView(InsightType.USER_SQL)
    }

    const lineOptions = (): LemonSelectOptions => {
        const res: LemonSelectOptions = {}
        insight.result?.forEach((result, index: number) => {
            res[index] = {
                label: 'Series',
                icon: <SeriesLetter seriesIndex={index} hasBreakdown={!!result.breakdown_value} />,
            }
        })
        return res
    }

    const onChangeSelect = (newValue): void => {
        setFilters({
            insight: InsightType.USER_SQL,
            user_sql: insight.result[newValue].source_query,
        })
        setActiveView(InsightType.USER_SQL)
    }

    return (
        <>
            <span style={{ padding: '0 4px' }}>•</span>
            {activeView === InsightType.TRENDS ||
            activeView === InsightType.STICKINESS ||
            activeView === InsightType.LIFECYCLE ? (
                <LemonSelect
                    value={null}
                    onChange={onChangeSelect}
                    options={lineOptions()}
                    type="stealth"
                    placeholder="View source SQL"
                    style={{
                        width: '100%',
                    }}
                />
            ) : (
                <LemonButton onClick={onClickSource} style={{ paddingLeft: 3, paddingRight: 3 }}>
                    <span style={{ fontSize: 14 }}>View source SQL</span>
                </LemonButton>
            )}
        </>
    )
}
