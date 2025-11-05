import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonInput, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonField } from '../LemonField'
import { LemonDialog, LemonDialogProps, LemonFormDialog, LemonFormDialogProps } from './LemonDialog'

type Story = StoryObj<typeof LemonDialog>
const meta: Meta<typeof LemonDialog> = {
    title: 'Lemon UI/Lemon Dialog',
    component: LemonDialog,
    args: {
        title: 'Do you want to do the thing?',
        description:
            'This is a simple paragraph that illustrates describing a decision the user is going to take. Dialogs typically ask a single question and provide 1-3 actions for responding. ',

        primaryButton: {
            children: 'Primary',
            onClick: () => alert('Primary Clicked!'),
        },

        secondaryButton: {
            children: 'Secondary',
            onClick: () => alert('Secondary Clicked!'),
        },

        tertiaryButton: {
            children: 'Tertiary',
            onClick: () => alert('Tertiary Clicked!'),
        },
    },
    parameters: {
        docs: {
            description: {
                component: `
[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)
                
Dialogs are blocking prompts that force a user decision or action. 
When a dialog presents a desctructive choice, the actions should align with that destructive / warning color palette options.

Dialogs are opened imperatively (i.e. calling \`LemonDialog.open()\`) whereas Modals are used declaratively.
            `,
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

export const Template: StoryFn<typeof LemonDialog> = (props: LemonDialogProps) => {
    const onClick = (): void => {
        LemonDialog.open(props)
    }
    return (
        <div>
            <div className="bg-border p-4">
                <LemonDialog {...props} inline />
            </div>
            <LemonButton type="primary" onClick={() => onClick()} className="mx-auto mt-2">
                Open as modal
            </LemonButton>
        </div>
    )
}

export const Minimal: Story = Template.bind({})
Minimal.args = {
    title: 'Notice',
    description: undefined,
    primaryButton: undefined,
    secondaryButton: undefined,
    tertiaryButton: undefined,
}

export const Customised: Story = Template.bind({})
Customised.args = {
    title: 'Are you sure you want to delete “FakeOrganization”?',
    description: (
        <>
            This action cannot be undone. If you opt to delete the organization and its corresponding events, the events
            will not be immediately removed. Instead these events will be deleted on a set schedule during non-peak
            usage times. <Link to="https://posthog.com">Learn more</Link>
        </>
    ),
    primaryButton: {
        children: 'Delete organization',
        status: 'danger',
        onClick: () => alert('Organization Deleted!'),
    },

    secondaryButton: {
        children: 'Cancel',
        onClick: () => alert('Cancelled!'),
    },

    tertiaryButton: {
        children: 'Delete organization and all corresponding events',
        status: 'danger',
        onClick: () => alert('Organization and all events deleted!'),
    },
}

export const Form: StoryObj = (props: LemonFormDialogProps): JSX.Element => {
    const onClick = (): void => {
        LemonDialog.openForm(props)
    }
    return (
        <div>
            <div className="bg-default p-4">
                <LemonFormDialog {...props} inline />
            </div>
            <LemonButton type="primary" onClick={() => onClick()} className="mx-auto mt-2">
                Open as modal
            </LemonButton>
        </div>
    )
}
Form.args = {
    title: 'This is a test',
    initialValues: { name: 'one' },
    description: undefined,
    tertiaryButton: undefined,
    content: (
        <LemonField name="name">
            <LemonInput placeholder="Please enter the new name" autoFocus />
        </LemonField>
    ),
}
Form.storyName = 'Category - Elements'
