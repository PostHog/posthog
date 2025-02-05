import { SideAction } from '@posthog/lemon-ui'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import {
    SettingsBar,
    SettingsBarProps,
    SettingsButton,
    SettingsMenu,
    SettingsToggle,
} from 'scenes/session-recordings/components/PanelSettings'

type Story = StoryObj<typeof SettingsBar>
const meta: Meta<typeof SettingsBar> = {
    title: 'Replay/Components/Settings Bar',
    component: SettingsBar,
    tags: ['autodocs'],
}
export default meta
const BasicTemplate: StoryFn<typeof SettingsBar> = (props: SettingsBarProps) => {
    const buttonSideAction: SideAction = {
        // icon: <IconChevronRight className="rotate-90" />,
        dropdown: {
            overlay: {},
        },
    }
    return (
        <SettingsBar {...props}>
            <SettingsToggle label="inactive toggle" active={false} />
            <SettingsToggle label="active toggle" active={true} />
            <SettingsButton label="inactive button" active={false} />
            <SettingsButton label="active button" active={true} />
            <SettingsMenu items={[{ label: 'inactive menu item', active: false, onClick: () => {} }]} label="menu" />
            <SettingsButton label="inactive button with side action" sideAction={buttonSideAction} active={false} />
            <SettingsButton label="active button with side action" sideAction={buttonSideAction} active={true} />
        </SettingsBar>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
