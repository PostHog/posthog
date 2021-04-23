import { Avatar, Card, Divider, List, Tooltip, Typography, Space } from 'antd'

import React from 'react'

const { Paragraph } = Typography

export interface TileParams {
    title: string
    targetPath: string
    hoverText?: string
    icon: JSX.Element
    color?: string
    class?: string
}

export interface TiledIconModuleProps {
    tiles: TileParams[]
    header?: string
    subHeader?: string
}

export function TiledIconModule({ tiles, header, subHeader }: TiledIconModuleProps): JSX.Element {
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
                        <a href={tile.targetPath}>
                            <Tooltip placement="bottom" title={tile.hoverText ? tile.hoverText : 'no hint'}>
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
