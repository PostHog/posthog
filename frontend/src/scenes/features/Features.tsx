import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
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
                caption="Release features in a controlled way. Track adoption in stages."
                buttons={
                    <LemonButton type="primary" to={urls.feature('new')}>
                        New feature
                    </LemonButton>
                }
                delimited
            />
            <LemonTable
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render(_, row) {
                            return (
                                <>
                                    <Link to={urls.feature(row.id)}>
                                        <div className="row-name">{row.name}</div>
                                    </Link>
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
