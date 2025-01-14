import { IconActivity } from '@posthog/icons'
import { Meta, Story } from '@storybook/react'

import { Button } from './Button'

const meta: Meta = {
    title: 'UI/Button',
}
export default meta

export const Default: Story = () => {
    return (
        <div className="flex flex-col gap-16 items-start surface-3000-primary">
            <div className="flex gap-4">
                <Button intent="primary">Primary</Button>
                <Button intent="primary" disabled>
                    Primary Disabled
                </Button>
                <Button intent="primary" disabledReason="This is a disabled reason">
                    Primary Disabled Reason
                </Button>
                <Button intent="primary" active>
                    Primary Active
                </Button>
            </div>

            <div className="flex gap-4">
                <Button intent="outline">Outline</Button>
                <Button intent="outline" disabled>
                    Outline Disabled
                </Button>
                <Button intent="outline" disabledReason="This is a disabled reason">
                    Outline Disabled Reason
                </Button>
                <Button intent="outline" active>
                    Outline Active
                </Button>
            </div>

            <div className="flex gap-4">
                <Button intent="muted">Muted</Button>
                <Button intent="muted" disabled>
                    Muted Disabled
                </Button>
                <Button intent="muted" disabledReason="This is a disabled reason">
                    Muted Disabled Reason
                </Button>
                <Button intent="muted" active>
                    Muted Active
                </Button>
            </div>

            <div className="flex gap-4">
                <Button intent="muted-darker">Muted Darker</Button>
                <Button intent="muted-darker" disabled>
                    Muted Darker Disabled
                </Button>
                <Button intent="muted-darker" disabledReason="This is a disabled reason">
                    Muted Darker Disabled Reason
                </Button>
                <Button intent="muted-darker" active>
                    Muted Darker Active
                </Button>
            </div>

            <div className="h-[42px] flex justify-between items-center gap-2 px-2 token-surface-3000-tertiary py-4">
                <Button intent="top-bar-tabs">Top Bar Tabs</Button>
                <Button intent="top-bar-tabs" active>
                    Top Bar Tabs Active
                </Button>
                <Button intent="top-bar-tabs" disabled>
                    Top Bar Tabs Disabled
                </Button>
                <Button intent="top-bar-tabs" disabledReason="This is a disabled reason">
                    Top Bar Tabs Disabled Reason
                </Button>
            </div>

            <div className="flex gap-4">
                <Button intent="primary" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                    Side Action
                </Button>
                <Button intent="outline" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                    Side Action
                </Button>
                <Button intent="muted" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                    Side Action
                </Button>
                <Button intent="muted-darker" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                    Side Action
                </Button>
                <Button intent="top-bar-tabs" sideAction={{ to: '/', onClick: () => {}, children: <IconActivity /> }}>
                    Side Action
                </Button>
            </div>
        </div>
    )
}
