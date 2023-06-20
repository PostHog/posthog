import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonTag as LemonTagComponent, LemonTagType } from './LemonTag'

export default {
    title: 'Lemon UI/Lemon Tag',
    component: LemonTagComponent,
} as ComponentMeta<typeof LemonTagComponent>

const ALL_COLORS: LemonTagType[] = [
    'primary',
    'highlight',
    'warning',
    'danger',
    'success',
    'default',
    'completion',
    'caution',
    'none',
]

const Template: ComponentStory<typeof LemonTagComponent> = (props) => {
    return (
        <div className="flex gap-1 flex-wrap">
            {ALL_COLORS.map((type) => (
                <LemonTagComponent key={type} {...props} type={type}>
                    {type}
                </LemonTagComponent>
            ))}
        </div>
    )
}

export const LemonTag = Template.bind({})
LemonTag.args = {}
