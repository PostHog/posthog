import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonFileInput } from 'lib/components/LemonFileInput/LemonFileInput'
import { createRef, useState } from 'react'

export default {
    title: 'Lemon UI/Lemon File Input',
    component: LemonFileInput,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        loading: { type: 'boolean', defaultValue: false },
        accept: { type: 'string', defaultValue: '.json' },
    },
} as ComponentMeta<typeof LemonFileInput>

const Template: ComponentStory<typeof LemonFileInput> = (props) => {
    const [singleValue, setSingleValue] = useState([] as any[])
    const [multipleValue, setMultipleValue] = useState([] as any[])

    const additionalDragTarget = createRef<HTMLDivElement>()

    return (
        <div className={'flex flex-col gap-4'}>
            <div>
                <h5>single file input</h5>
                <LemonFileInput
                    loading={props.loading}
                    {...props}
                    multiple={false}
                    value={singleValue}
                    onChange={(newValue) => setSingleValue(newValue)}
                />
            </div>
            <div>
                <h5>multi file input</h5>
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
                    also a drag target
                </div>
                <LemonFileInput
                    loading={props.loading}
                    {...props}
                    multiple={true}
                    value={multipleValue}
                    onChange={(newValue) => setMultipleValue(newValue)}
                    alternativeDropTargetRef={additionalDragTarget}
                />
            </div>
        </div>
    )
}

export const Default = Template.bind({})
