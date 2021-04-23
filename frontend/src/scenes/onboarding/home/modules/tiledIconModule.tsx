import { Avatar, Card, Divider, List, Tooltip, Typography, Space } from 'antd'

import React from 'react'
import { useActions } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

const { Paragraph } = Typography

export interface TileParams {
    title: string
    targetPath: string
    openInNewTab?: boolean
    hoverText?: string
    icon: JSX.Element
    class?: string
}

export interface TiledIconModuleProps {
    tiles: TileParams[]
    header?: string
    subHeader?: string
    analyticsModuleKey?: string
}

export function TiledIconModule({ tiles, header, subHeader, analyticsModuleKey }: TiledIconModuleProps): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)
    return (
        <Card className="home-module-card">
            <h2 id="name" className="subtitle">
                {header}
            </h2>
            <Paragraph>{subHeader}</Paragraph>
            <Divider />
            <Space direction={'horizontal'}>
                <List
                    style={{ overflowY: 'scroll' }}
                    grid={{}}
                    dataSource={tiles}
                    renderItem={(tile) => (
                        <a
                            href={tile.targetPath}
                            target={tile.openInNewTab ? '_blank' : '_self'}
                            onClick={() => {
                                reportProjectHomeItemClicked(analyticsModuleKey ?? '', tile.title)
                            }}
                        >
                            <Tooltip placement="bottom" title={tile.hoverText ? tile.hoverText : ''}>
                                <List.Item className="insight-container" key={tile.title}>
                                    <Avatar
                                        size={85}
                                        shape={'square'}
                                        className={tile.class ? tile.class : 'thumbnail-tile-default'}
                                        icon={tile.icon}
                                    >
                                        {tile.title}
                                    </Avatar>
                                    <h4 className={'insight-text'}>{tile.title}</h4>
                                </List.Item>
                            </Tooltip>
                        </a>
                    )}
                />
            </Space>
        </Card>
    )
}
