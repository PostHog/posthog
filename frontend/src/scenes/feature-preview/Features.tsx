import './Features.scss'
import { featuresLogic } from './featuresLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable } from '@posthog/lemon-ui'

export function Features(): JSX.Element {
    return (
        <div className="feature-scene">
            <LemonTable
                columns={[
                    // use row name and row description (see feature flages page)
                    {
                        title: 'Name',
                        key: 'name',
                        render(_, row) {
                            return (
                                <div>
                                    <div className="row-name">{row.name}</div>
                                    <div className="row-description">{row.description}</div>
                                    <div className="row-description">{row.description}</div>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                    },
                    {
                        title: 'imageURL',
                        dataIndex: 'imageUrl',
                    },
                    {
                        title: 'documentationUrl',
                        dataIndex: 'documentationUrl',
                    },
                    {
                        title: 'flagKey',
                        dataIndex: 'flagKey',
                    },
                ]}
                dataSource={[
                    {
                        id: 1779,
                        name: 'Enable viewing console logs in session recordings',
                        description: 'this is a wonderful feature',
                        status: 'beta',
                        key: 'session-recording-console',
                    },
                    {
                        id: 1526,
                        name: '',
                        key: 'croatia-banner',
                    },
                    {
                        id: 1502,
                        name: '',
                        key: 'nav-bar-color-2',
                    },
                ]}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Features,
    logic: featuresLogic,
}
