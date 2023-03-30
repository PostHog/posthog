import { LemonButton, LemonDivider, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { featuresLogic } from './featuresLogic'

export const scene: SceneExport = {
    component: Features,
    logic: featuresLogic,
}

export function Features(): JSX.Element {
    const { features } = useValues(featuresLogic)

    return (
        <>
            <PageHeader
                title="Features"
                caption="Plan the future and control the present of all your features."
                buttons={
                    <LemonButton type="primary" to={urls.feature('new')}>
                        New feature
                    </LemonButton>
                }
            />
            <LemonDivider className="my-4" />
            <LemonTable
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render(_, row) {
                            return (
                                <>
                                    <div className="row-name">{row.name}</div>
                                    <div className="row-description">{row.description}</div>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Stage',
                        dataIndex: 'stage',
                    },
                ]}
                dataSource={features}
            />
        </>
    )
}
