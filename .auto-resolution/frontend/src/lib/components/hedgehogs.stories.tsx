import { Meta } from '@storybook/react'

import { LemonTable } from '@posthog/lemon-ui'

import * as hedgehogs from './hedgehogs'

interface HedgehogDefinition {
    name: string
    hedgehog: (...args: any[]) => JSX.Element
}

const allHedgehogs: HedgehogDefinition[] = Object.entries(hedgehogs).map(([key, Hedgehog]) => ({
    name: key,
    hedgehog: Hedgehog,
}))

const meta: Meta = {
    title: 'Lemon UI/Hog illustrations',
    tags: ['test-skip', 'autodocs'], // Not valuable to take snapshots of these hedgehogs
    parameters: {
        docs: {
            description: {
                component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3775%3A2092)

Our hedgehog has many professions so it’s vital you choose the correct one for whatever project
or page you are working on.s

Singular hedgehog illustrations should be kept in a 200x200px frame
and scaled up or down accordingly. Wider hedgehog frames containing one or more will keep the
same height of 200px but the width may change dependant on the illustration.

As we continue to
grow more and more hedgehogs of different professions and positions will appear, but if you have
a specific idea in mind, please submit new hedgehog requests to Lottie our Graphic Designer and
she will get to it dependant on work load.
`,
            },
        },
    },
}
export default meta
export function Library(): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <LemonTable
                dataSource={allHedgehogs}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderName(name) {
                            return <code>{`<${name as string} />`}</code>
                        },
                    },
                    {
                        title: 'Hedgehog',
                        key: 'hedgehog',
                        dataIndex: 'hedgehog',
                        render: function RenderHedgehog(Hedgehog) {
                            Hedgehog = Hedgehog as HedgehogDefinition['hedgehog']
                            return (
                                <div className="h-40">
                                    <Hedgehog className="max-h-full w-auto object-contain" />
                                </div>
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
