import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { LemonTable } from 'lib/components/LemonTable'
import React, { useEffect, useRef, useState } from 'react'
import { JSONTree } from 'react-json-tree'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    Chart,
    ChartItem,
    ChartType,
} from 'chart.js'
import { GraphType } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'

function convertArrayToString(payload): any {
    if (!payload) {
        return []
    }

    return payload.map((item) => {
        const newItem = {}
        Object.keys(item).map((key) => {
            if (Array.isArray(item[key])) {
                newItem[key] = JSON.stringify(item[key])
            } else {
                newItem[key] = item[key]
            }
        })
        return newItem
    })
}

export function UserSQLInsight(): JSX.Element {
    const { insight } = useValues(insightLogic)
    const [cleanedResult, setResult] = useState(convertArrayToString(insight.result))
    const [modalVisible, setModalVisible] = useState(false)
    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const myLineChart = useRef<Chart<ChartType, any, string>>()
    const [xValue, setX] = useState(null)
    const [yValue, setY] = useState(null)

    useEffect(() => {
        setResult(convertArrayToString(insight.result))
    }, [insight.result])

    const keys = Object.keys(cleanedResult?.[0] || [])

    const columns = keys.map((key) => {
        return {
            title: key,
            dataIndex: key,
            render: function RenderKey(result): JSX.Element {
                try {
                    const data = JSON.parse(result)
                    return (
                        <div style={{ minWidth: 300 }}>
                            <JSONTree
                                data={data}
                                shouldExpandNode={() => false}
                                theme={{
                                    scheme: 'bright',
                                    author: 'chris kempson (http://chriskempson.com)',
                                    base00: '#000000',
                                    base01: '#303030',
                                    base02: '#505050',
                                    base03: '#b0b0b0',
                                    base04: '#d0d0d0',
                                    base05: '#e0e0e0',
                                    base06: '#f5f5f5',
                                    base07: '#ffffff',
                                    base08: '#fb0120',
                                    base09: '#fc6d24',
                                    base0A: '#fda331',
                                    base0B: '#a1c659',
                                    base0C: '#76c7b7',
                                    base0D: '#6fb3d2',
                                    base0E: '#d381c3',
                                    base0F: '#be643c',
                                }}
                            />
                        </div>
                    )
                } catch {
                    return <div>{result}</div>
                }
            },
        }
    })

    const isResultSingle = (): boolean => {
        return cleanedResult?.length === 1 && Object.keys(cleanedResult[0]).length === 1
    }

    const getSingleResult = (result): number => {
        return Object.values(result[0])[0] as number
    }

    const onChangeX = (newValue) => {
        setX(newValue)
    }

    const onChangeY = (newValue) => {
        setY(newValue)
    }

    const onCloseModal = () => {
        setModalVisible(false)
    }

    const onOpenModal = () => {
        setModalVisible(true)
    }

    const columnOptions = (): LemonSelectOptions => {
        const res: LemonSelectOptions = {}
        if (cleanedResult.length) {
            Object.keys(cleanedResult[0]).forEach((key) => {
                res[key] = {
                    label: key,
                }
            })
        }
        return res
    }

    const createChart = () => {
        const myChartRef = chartRef.current?.getContext('2d')

        const x = []
        const y = []
        
        if (xValue && yValue) {
            cleanedResult.forEach((item) => {
                x.push(item[xValue])
                y.push(item[yValue])
            })
        }

        const labels = x;
        const data = {
        labels: labels,
        datasets: [{
            label: 'Series',
            data: y,
            fill: false,
            borderColor: 'rgb(75, 192, 192)',
            tension: 0.1
        }]
        };


        myLineChart.current = new Chart(myChartRef as ChartItem, {
            type: GraphType.Line,
            data: data,
            // options: {
            //     scales: {
            //         x: {
            //             min: 0,
            //             max: 10,
            //             ticks: {
            //                 stepSize: 1
            //             }
            //         },
            //         y: {
            //             min: 0,
            //             max: 10,
            //             ticks: {
            //                 stepSize: 1
            //             }
            //         }
            //     }
            // },
        })
    }

    return <div>
        <LemonRow>
            <LemonButton onClick={onOpenModal} >Create visualizations</LemonButton>
            <LemonButton onClick={() => {
                setX(null)
                setY(null)
            }} >Clear visualizations</LemonButton>
        </LemonRow>

        {(xValue && yValue) ? <canvas ref={chartRef} /> : isResultSingle() ? (
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    margin: 30,
                    fontSize: 55,
                    fontWeight: 'bold',
                }}
            >
                {getSingleResult(cleanedResult)}
            </div>
        ) : (
            <LemonTable
                columns={columns}
                size="small"
                rowKey="0"
                dataSource={cleanedResult}
                emptyState="This property value is an empty object."
                pagination={{ pageSize: 100 }}
            />
        )}
        <LemonModal
            title="New visualization"
            destroyOnClose
            onCancel={onCloseModal}
            visible={modalVisible}
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-cancel"
                        loading={false}
                        style={{ marginRight: '0.5rem' }}
                        onClick={onCloseModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="new-dashboard-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="dashboard-submit"
                        loading={false}
                        onClick={() => {
                            onCloseModal()
                            createChart()
                        }}
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <LemonSelect placeholder='Select X axis' value={null} onChange={onChangeX} options={columnOptions()} >

            </LemonSelect>
            <LemonSelect placeholder='Select Y axis' value={null} onChange={onChangeY} options={columnOptions()} >

            </LemonSelect>
            
        </LemonModal>
    </div>
}
