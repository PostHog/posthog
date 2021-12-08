import { Button } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { experimentLogic } from './experimentLogic'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

const NEW_EXPERIMENT = {
    id: 'new',
}

export function Experiments(): JSX.Element {
    const { setOpenExperiment } = useActions(experimentsLogic)
    const { createNewExperimentFunnel } = useActions(experimentLogic)

    return (
        <div>
            <PageHeader title="Experiments" caption="Experiments" />
            <div className="mb float-right">
                <Button
                    type="primary"
                    data-attr="create-experiment"
                    onClick={() => {
                        setOpenExperiment(NEW_EXPERIMENT)
                        createNewExperimentFunnel()
                    }}
                    icon={<PlusOutlined />}
                >
                    New Experiment
                </Button>
            </div>
        </div>
    )
}
