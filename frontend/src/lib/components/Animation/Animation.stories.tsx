import * as React from 'react'
import { animations, AnimationType } from '../../animations/animations'
import { Meta } from '@storybook/react'
import { LemonTable } from '../LemonTable'
import { Animation } from 'lib/components/Animation/Animation'

export default {
    title: 'Layout/Animations',
    parameters: {
        options: { showPanel: false },
        docs: {
            description: {
                component:
                    'Animations are [LottieFiles.com](https://lottiefiles.com/) animations that we load asynchronously.',
            },
        },
    },
} as Meta

export function Animations(): JSX.Element {
    return (
        <LemonTable
            dataSource={Object.keys(animations).map((key) => ({ key }))}
            columns={[
                {
                    title: 'Code',
                    key: 'code',
                    dataIndex: 'key',
                    render: function RenderCode(name) {
                        return <code>{`<Animation type="${name as string}" />`}</code>
                    },
                },
                {
                    title: 'Animation',
                    key: 'animation',
                    dataIndex: 'key',
                    render: function RenderAnimation(key) {
                        return <Animation type={key as AnimationType} />
                    },
                },
            ]}
        />
    )
}
