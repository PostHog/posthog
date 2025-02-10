import { SideAction } from '@posthog/lemon-ui'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { IconReplay } from 'lib/lemon-ui/icons'
import {
    SettingsBar,
    SettingsBarProps,
    SettingsButton,
    SettingsMenu,
    SettingsToggle,
} from 'scenes/session-recordings/components/PanelSettings'

type StoryProps = SettingsBarProps & { icon?: JSX.Element }
type Story = StoryObj<StoryProps>
const meta: Meta<StoryProps> = {
    title: 'Replay/Components/Settings Bar',
    component: SettingsBar,
    tags: ['autodocs'],
}
export default meta
const BasicTemplate: StoryFn<StoryProps> = ({ icon, ...props }) => {
    const buttonSideAction: SideAction = {
        dropdown: {
            overlay: {},
        },
    }
    return (
        <SettingsBar {...props}>
            <SettingsToggle label="inactive toggle" active={false} icon={icon} />
            <SettingsToggle label="active toggle" active={true} icon={icon} />
            <SettingsButton label="inactive button" active={false} icon={icon} />
            <SettingsButton label="active button" active={true} icon={icon} />
            <SettingsMenu
                items={[{ label: 'inactive menu item', active: false, onClick: () => {} }]}
                label="menu"
                icon={icon}
            />
            <SettingsButton
                label="inactive button with side action"
                sideAction={buttonSideAction}
                active={false}
                icon={icon}
            />
            <SettingsButton
                label="active button with side action"
                sideAction={buttonSideAction}
                active={true}
                icon={icon}
            />
        </SettingsBar>
    )
}

export const Default: Story = {
    render: BasicTemplate,
    args: {},
}

export const WithIcons: Story = {
    render: BasicTemplate,
    args: {
        icon: <IconReplay />,
    },
}
