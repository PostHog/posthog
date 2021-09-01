import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'

import { Layout, Space } from 'antd'

export function Home(): JSX.Element {
    return (
        <Layout className={'home-page'}>
            <div style={{ marginBottom: 128 }}>
                <Space direction="vertical">
                    <PageHeader title="Product Tours" caption={'Manage and create guided tours of your product.'} />
                </Space>
            </div>
        </Layout>
    )
}
