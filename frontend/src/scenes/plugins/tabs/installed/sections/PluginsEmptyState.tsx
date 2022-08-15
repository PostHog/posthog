import { CaretRightOutlined } from '@ant-design/icons'
import { Button, Col, Empty, Row, Skeleton } from 'antd'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginTab } from 'scenes/plugins/types'
import { canGloballyManagePlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'

export function PluginsEmptyState(): JSX.Element {
    const { setPluginTab } = useActions(pluginsLogic)
    const { loading } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            {loading ? (
                <>
                    <Subtitle
                        subtitle={
                            <>
                                {' '}
                                <CaretRightOutlined /> {'Enabled apps'}{' '}
                            </>
                        }
                        buttons={<Skeleton.Button style={{ width: 150 }} />}
                    />
                    <PluginLoading />
                </>
            ) : (
                <>
                    <Subtitle subtitle="Installed apps" />
                    <Row gutter={16} style={{ marginTop: 16 }}>
                        <Col span={24}>
                            <Empty description={<span>You haven't installed any apps yet</span>}>
                                {canGloballyManagePlugins(user?.organization) && (
                                    <Button type="default" onClick={() => setPluginTab(PluginTab.Repository)}>
                                        Open the App Repository
                                    </Button>
                                )}
                            </Empty>
                        </Col>
                    </Row>
                </>
            )}
        </>
    )
}
