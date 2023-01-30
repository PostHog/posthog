import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { createRef, useState } from 'react'

export default {
    title: 'Lemon UI/Lemon File Input',
    component: LemonFileInput,
    argTypes: {
        loading: { type: 'boolean', defaultValue: false },
        accept: { type: 'string', defaultValue: '.json' },
    },
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonFileInput>

const Template: ComponentStory<typeof LemonFileInput> = (props) => {
    const [singleValue, setSingleValue] = useState([] as any[])
    const [multipleValue, setMultipleValue] = useState([] as any[])
    const [extraTargetValue, setExtraTargetValue] = useState([] as any[])

    const additionalDragTarget = createRef<HTMLDivElement>()

    return (
        <div className={'flex flex-col gap-4'}>
            <div>
                <h5>Single file input</h5>
                <LemonFileInput
                    loading={props.loading}
                    {...props}
                    multiple={false}
                    value={singleValue}
                    onChange={(newValue) => setSingleValue(newValue)}
                />
            </div>
            <div>
                <h5>Multi file input</h5>
                <LemonFileInput
                    loading={props.loading}
                    {...props}
                    multiple={true}
                    value={multipleValue}
                    onChange={(newValue) => setMultipleValue(newValue)}
                />
            </div>
            <div>
                <h5>Extra drag and drop target</h5>
                <div ref={additionalDragTarget} className={'h-12 w-full border flex items-center justify-center'}>
                    This area is also a drag target
                </div>
                <LemonFileInput
                    loading={props.loading}
                    {...props}
                    multiple={true}
                    value={extraTargetValue}
                    onChange={(newValue) => setExtraTargetValue(newValue)}
                    alternativeDropTargetRef={additionalDragTarget}
                />
            </div>
        </div>
    )
}

export const Default = Template.bind({})
