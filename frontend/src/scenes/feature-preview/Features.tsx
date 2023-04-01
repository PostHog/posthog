import './Features.scss'
import { featuresLogic } from './featuresLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonSwitch, LemonButton } from '@posthog/lemon-ui'
import { posthog } from 'posthog-js'
import { PageHeader } from 'lib/components/PageHeader'

export function Features(): JSX.Element {
    return (
        <div className="feature-scene">
            <PageHeader title="Feature Previews" />
            <LemonTable
                className="mt-4"
                columns={[
                    // change to lemon switch
                    // add images
                    // add give feedback button (check out how this works in the top menu), to pop open the feedback button
                    {
                        key: 'imageUrl',
                        width: 0,
                        render(_, row) {
                            return !!row.imageUrl && <img src={row.imageUrl} className="border rounded w-80" />
                        },
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render(_, row) {
                            return (
                                <div>
                                    <div className="row-name">{row.name}</div>
                                    <div className="row-description">
                                        {row.description}
                                        {row.documentationUrl && (
                                            <>
                                                &nbsp;<a href={row.documentationUrl}>Read the docs</a>
                                            </>
                                        )}
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        // make it so this is _either_ switch on _or_ if it's a register interest
                        title: 'stage',
                        dataIndex: 'flagKey',
                        width: 0,
                        render(key, row) {
                            let option
                            if (row.stage == 'beta') {
                                const isEnabled = posthog.isFeatureEnabled(key as string)
                                option = (
                                    <LemonSwitch
                                        checked={isEnabled}
                                        label={isEnabled ? 'Enabled' : 'Disabled'}
                                        onChange={() => {
                                            posthog.updateFeaturePreviewEnrollment(key as string, !isEnabled)
                                        }}
                                    />
                                )
                            } else {
                                option = <LemonButton type="primary">Get notified when available</LemonButton>
                            }

                            return <div>{option}</div>
                        },
                    },
                ]}
                dataSource={posthog.getFeaturePreviews()}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Features,
    logic: featuresLogic,
}
