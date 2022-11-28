import { useActions } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { Card } from 'antd'
import { AppstoreAddOutlined } from '@ant-design/icons'

export const NoDashboards = (): JSX.Element => {
    const { addDashboard } = useActions(newDashboardLogic)

    return (
        <div className="mt-4">
            <p>Create your first dashboard:</p>
            <div className="flex justify-center items-center gap-4">
                <Card
                    title="Empty"
                    size="small"
                    style={{ width: 200, cursor: 'pointer' }}
                    onClick={() =>
                        addDashboard({
                            name: 'New Dashboard',
                            useTemplate: '',
                        })
                    }
                >
                    <div style={{ textAlign: 'center', fontSize: 40 }}>
                        <AppstoreAddOutlined />
                    </div>
                </Card>
                <Card
                    title="App Default"
                    size="small"
                    style={{ width: 200, cursor: 'pointer' }}
                    onClick={() =>
                        addDashboard({
                            name: 'Web App Dashboard',
                            useTemplate: 'DEFAULT_APP',
                        })
                    }
                >
                    <div style={{ textAlign: 'center', fontSize: 40 }}>
                        <AppstoreAddOutlined />
                    </div>
                </Card>
            </div>
        </div>
    )
}
