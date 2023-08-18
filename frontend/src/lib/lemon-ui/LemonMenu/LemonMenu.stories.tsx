import { Meta, StoryFn, StoryObj } from '@storybook/react'
import {
    LemonMenuOverlay as LemonMenuOverlayComponent,
    LemonMenuOverlayProps,
    LemonMenuItems,
    LemonMenuSection,
} from './LemonMenu'
import { Splotch, SplotchColor } from '../Splotch'

type Story = StoryObj<typeof LemonMenuOverlayComponent>
const meta: Meta<typeof LemonMenuOverlayComponent> = {
    title: 'Lemon UI/Lemon Menu',
    component: LemonMenuOverlayComponent,
    parameters: {
        docs: {
            description: {
                component: `
Implement all sorts of menus easily with \`LemonMenu\`.
                
Note: These stories render \`LemonMenuOverlay\` instead of \`LemonMenu\` so that the contents are is shown outright.
This enables intuitive preview of the component, along with snapshotting, but in code always use \`LemonMenu\`.`,
            },
        },
    },
    args: {
        items: [
            { label: 'Alert', onClick: () => alert('Hello there.') },
            { label: 'Do nothing' },
            { label: 'Do nothing, with a highlight', active: true },
        ] as LemonMenuItems,
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonMenuOverlayComponent> = (props: LemonMenuOverlayProps) => {
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
                <LemonMenuOverlayComponent {...props} />
            </div>
        </div>
    )
}

export const Flat: Story = {
    render: Template,
    args: {},
}

export const SectionedItems: Story = {
    render: Template,

    args: {
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
    },
}

export const NestedMenu: Story = {
    render: Template,

    args: {
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
                    {
                        label: 'Open matryoshka',
                        items: [
                            {
                                label: 'Open matryoshka',
                                items: [
                                    {
                                        label: 'Baby matryoshka!',
                                    },
                                ],
                            },
                        ],
                    },
                ],
                footer: (
                    <div className="flex items-center h-10 px-2 rounded bg-mid text-muted">I am a custom footer!</div>
                ),
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
    },
}
