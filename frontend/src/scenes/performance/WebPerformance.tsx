import React from 'react'
import { Button, Col, Row } from 'antd'
import './WebPerformance.scss'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import { AnyPropertyFilter, EventsTableRowItem, PropertyOperator } from '~/types'
import { webPerformanceLogic, WebPerformancePage } from 'scenes/performance/webPerformanceLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { EventsTable } from 'scenes/events'
import { EyeOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { WebPerformanceWaterfallChart } from 'scenes/performance/WebPerformanceWaterfallChart'

/*
 * link to SessionRecording from table and chart
 * show histogram of pageload instead of table
 */

export const webPerformancePropertyFilters: AnyPropertyFilter[] = [
    {
        key: '$performance_raw',
        value: 'is_set',
        operator: PropertyOperator.IsSet,
        type: 'event',
    },
]

const EventsWithPerformanceTable = (): JSX.Element => {
    const { setEventToDisplay } = useActions(webPerformanceLogic)

    return (
        <EventsTable
            fixedFilters={{
                properties: webPerformancePropertyFilters,
            }}
            sceneUrl={urls.webPerformance()}
            fetchMonths={1}
            pageKey={`webperformance-${JSON.stringify(webPerformancePropertyFilters)}`}
            showPersonColumn={false}
            showCustomizeColumns={false}
            showExport={false}
            showAutoload={false}
            showEventFilter={false}
            showRowExpanders={false}
            showActionsButton={false}
            linkPropertiesToFilters={false}
            data-attr="waterfall-events-table"
            startingColumns={['$current_url', '$performance_page_loaded']}
            fixedColumns={[
                {
                    render: function RenderViewButton(_: any, { event }: EventsTableRowItem) {
                        if (!event) {
                            return { props: { colSpan: 0 } }
                        }
                        return (
                            <div>
                                <Button
                                    data-attr={`view-waterfall-button-${event?.id}`}
                                    icon={<EyeOutlined />}
                                    onClick={() => {
                                        console.log({ event }, 'setting event to display')
                                        setEventToDisplay(event)
                                    }}
                                >
                                    View waterfall chart
                                </Button>
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}

export const WebPerformance = (): JSX.Element => {
    const { currentPage } = useValues(webPerformanceLogic)

    return (
        <div className="web-performance">
            <PageHeader
                title={
                    <Row align="middle">
                        Web Performance
                        <LemonTag type="warning" style={{ marginLeft: 8 }}>
                            Early Preview
                        </LemonTag>
                    </Row>
                }
                caption={
                    currentPage === WebPerformancePage.TABLE ? (
                        <div>
                            <p>
                                Shows page view events where performance information has been captured. Not all events
                                have all performance information.
                            </p>
                            <p>
                                To capture performance information you must be using posthog-js and set{' '}
                                <code>_capture_performance</code> to true. See the{' '}
                                <a href="https://posthog.com/docs/integrate/client/js#config" target="_blank">
                                    config instructions in our handbook
                                </a>
                            </p>
                        </div>
                    ) : null
                }
            />
            <Row gutter={[0, 32]}>
                <Col span={24}>
                    {currentPage === WebPerformancePage.TABLE ? (
                        <EventsWithPerformanceTable />
                    ) : currentPage === WebPerformancePage.WATERFALL_CHART ? (
                        <WebPerformanceWaterfallChart />
                    ) : (
                        <>404?</>
                    )}
                </Col>
            </Row>
        </div>
    )
}

export const scene: SceneExport = {
    component: WebPerformance,
    logic: webPerformanceLogic,
    paramsToProps: () => ({ sceneUrl: urls.webPerformance() }),
}
