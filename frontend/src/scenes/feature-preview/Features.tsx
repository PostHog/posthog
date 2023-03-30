import './Features.scss'
import { featuresLogic } from './featuresLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTable, LemonSwitch, LemonButton } from '@posthog/lemon-ui'

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
                                        {row.description}&nbsp;<a href={row.documentationUrl}>Read the docs</a>
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        // make it so this is _either_ switch on _or_ if it's a register interest
                        title: 'Status',
                        key: 'status',
                        render(_, row) {
                            let option
                            if (row.status == 'beta') {
                                option = <LemonSwitch checked={false} label="Enabled" onChange={() => {}} />
                            } else {
                                option = <LemonButton type="primary">Get Notified When Available</LemonButton>
                            }

                            return <div>{option}</div>
                        },
                    },
                ]}
                dataSource={[
                    {
                        id: 1779,
                        name: 'Enable viewing console logs in session recordings',
                        description: 'this is a wonderful feature',
                        documentationUrl: 'https://example.com/',
                        imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                        status: 'beta',
                        flagKey: 'session-recording-console',
                    },
                    {
                        id: 1779,
                        name: 'Enable viewing console logs in session recordings',
                        description: 'this is a wonderful feature',
                        documentationUrl: 'https://example.com/',
                        imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                        status: 'alpha',
                        flagKey: 'session-recording-console',
                    },
                    {
                        id: 1779,
                        name: 'Enable viewing console logs in session recordings',
                        description: 'this is a wonderful feature',
                        documentationUrl: 'https://example.com/',
                        imageUrl: 'https://www.iana.org/_img/2022/iana-logo-header.svg',
                        status: 'beta',
                        flagKey: 'session-recording-console',
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
