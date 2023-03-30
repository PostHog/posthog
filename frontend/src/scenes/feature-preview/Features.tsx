import './Features.scss'
import { featuresLogic } from './featuresLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonSwitch, LemonButton } from '@posthog/lemon-ui'
import { FeaturePreview } from 'posthog-js'

export function Features(): JSX.Element {
    return (
        <div className="feature-scene">
            <LemonTable
                columns={[
                    // change to lemon switch
                    // add images
                    // add give feedback button (check out how this works in the top menu), to pop open the feedback button
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
                        dataIndex: 'stage',
                        render(stage) {
                            let option
                            if (stage == 'beta') {
                                option = <LemonSwitch checked={false} label="Enabled" onChange={() => {}} />
                            } else {
                                option = <LemonButton type="primary">Get notified when available</LemonButton>
                            }

                            return <div>{option}</div>
                        },
                    },
                ]}
                dataSource={
                    [
                        {
                            name: 'Enable viewing console logs in session recordings',
                            description: 'this is a wonderful feature',
                            documentationUrl: 'https://example.com/',
                            imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                            stage: 'beta',
                            flagKey: 'session-recording-console',
                        },
                        {
                            name: 'Enable viewing console logs in session recordings',
                            description: 'this is a wonderful feature',
                            documentationUrl: 'https://example.com/',
                            imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                            stage: 'alpha',
                            flagKey: 'session-recording-console',
                        },
                        {
                            name: 'Enable viewing console logs in session recordings',
                            description: 'this is a wonderful feature',
                            documentationUrl: 'https://example.com/',
                            imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                            stage: 'beta',
                            flagKey: 'session-recording-console',
                        },
                    ] as FeaturePreview[]
                }
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Features,
    logic: featuresLogic,
}
