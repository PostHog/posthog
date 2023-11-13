import { useActions } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { Card } from 'antd'
// eslint-disable-next-line no-restricted-imports
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
                    <div className="text-4xl text-center">
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
                    <div className="text-4xl text-center">
                        <AppstoreAddOutlined />
                    </div>
                </Card>
            </div>
        </div>
    )
}
