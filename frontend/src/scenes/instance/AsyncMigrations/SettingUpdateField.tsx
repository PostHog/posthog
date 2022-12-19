import { useState } from 'react'
import { Button, Col, Divider, Input, Row } from 'antd'
import { useActions } from 'kea'
import { asyncMigrationsLogic } from './asyncMigrationsLogic'
import { InstanceSetting } from '~/types'

export function SettingUpdateField({ setting }: { setting: InstanceSetting }): JSX.Element {
    const { updateSetting } = useActions(asyncMigrationsLogic)

    const [inputValue, setInputValue] = useState<string>(String(setting.value))

    return (
        <div key={setting.key}>
            <h4>{setting.key}</h4>
            <p>{setting.description}</p>
            <Row gutter={[8, 8]}>
                <Col span={8}>
                    <Input value={inputValue} onChange={(e) => setInputValue(e.target.value)} />
                </Col>
                <Col span={16}>
                    <Button
                        disabled={String(setting.value) === inputValue}
                        type="primary"
                        onClick={() => updateSetting(setting.key, inputValue)}
                    >
                        Update
                    </Button>
                </Col>
            </Row>
            <Divider />
        </div>
    )
}
