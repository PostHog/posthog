import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonMenu as LemonMenuComponent, LemonMenuItems, LemonMenuProps, LemonMenuSection } from './LemonMenu'
import { Splotch, SplotchColor } from '../Splotch'

export default {
    title: 'Lemon UI/Lemon Menu',
    component: LemonMenuComponent,
    argTypes: {
        items: {
            defaultValue: [
                { label: 'Alert', onClick: () => alert('Hello there.') },
                { label: 'Do nothing' },
                { label: 'Do nothing, with a highlight', active: true },
            ] as LemonMenuItems,
        },
    },
} as ComponentMeta<typeof LemonMenuComponent>

const Template: ComponentStory<typeof LemonMenuComponent> = (props: LemonMenuProps) => {
    return (
        <div className="Popover">
            <div
                className="Popover__box"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    opacity: 1,
                    width: 'fit-content',
                }}
            >
                <LemonMenuComponent {...props} />
            </div>
        </div>
    )
}

export const Flat = Template.bind({})
Flat.args = {}

export const WithSections = Template.bind({})
WithSections.args = {
    items: [
        {
            title: 'Reptiles',
            items: [
                { label: 'Cobra', onClick: () => alert('Sssss') },
                { label: 'Boa', onClick: () => alert('Rrrrr') },
            ],
        },
        {
            title: 'Mammals',
            items: [
                { label: 'Dog', onClick: () => alert('Woof') },
                { label: 'Cat', onClick: () => alert('Meow') },
            ],
        },
        {
            title: 'Birds',
            items: [
                { label: 'Eagle', onClick: () => alert('Screech') },
                { label: 'Owl', onClick: () => alert('Hoot') },
            ],
        },
    ] as LemonMenuSection[],
}

export const WithNestedMenus = Template.bind({})
WithNestedMenus.args = {
    items: [
        {
            items: [
                { label: 'Refresh' },
                {
                    label: 'Set color',
                    items: [
                        { icon: <Splotch color={SplotchColor.Purple} />, label: 'Purple' },
                        { icon: <Splotch color={SplotchColor.Blue} />, label: 'Blue' },
                        { icon: <Splotch color={SplotchColor.Green} />, label: 'Green', active: true },
                    ],
                },
            ],
            footer: <div className="flex items-center h-10 px-2 rounded bg-mid text-muted">I am a custom footer!</div>,
        },
        {
            items: [
                {
                    label: 'Detonate charges',
                    onClick: () => alert('Twrmzlzktdzuntqniuqpmodxmokjwolbbf'),
                    status: 'danger',
                },
            ],
        },
    ] as LemonMenuSection[],
}
