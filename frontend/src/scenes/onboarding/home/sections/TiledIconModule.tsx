import { Avatar, Card, Divider, List, Typography, Space } from 'antd'

import React from 'react'
import { useActions } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TiledIconModuleProps } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'

const { Paragraph } = Typography

export function TiledIconModule({ tiles, header, subHeader, analyticsModuleKey }: TiledIconModuleProps): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)
    return (
        <Card className="home-page section-card">
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
                            rel={tile.openInNewTab ? 'noopener' : ''}
                            onClick={() => {
                                reportProjectHomeItemClicked(analyticsModuleKey ?? '', tile.title)
                            }}
                        >
                            <Tooltip placement="top" title={tile.hoverText ? tile.hoverText : ''}>
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
