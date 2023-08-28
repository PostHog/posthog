import { Meta, StoryFn } from '@storybook/react'
import { NotebookAddButton } from 'scenes/notebooks/NotebookAddButton/NotebookAddButton'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { NotebookNodeType } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'

export default {
    title: 'Scenes-App/Notebooks/Components/Notebook Add Button',
    component: NotebookAddButton,
} as Meta<typeof NotebookAddButton>

const allNotebooks = [
    {
        title: 'my amazing notebook',
        short_id: 'abc',
    },
    { title: 'and another amazing notebook', short_id: 'def' },
    { title: 'an empty notebook', short_id: 'ghi' },
]

const Template: StoryFn<typeof NotebookAddButton> = (props) => {
    useFeatureFlags([FEATURE_FLAGS.NOTEBOOKS])
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/notebooks/': (req, res, ctx) => {
                const contains = req.url.searchParams.get('contains')
                const sessionRecordingId = contains?.split(':')[1]
                const unfiltered = contains == null && sessionRecordingId === undefined

                if (unfiltered) {
                    return [200, { count: 3, results: allNotebooks }]
                }

                if (sessionRecordingId === 'there_are_no_notebooks') {
                    return [200, { count: 0, results: [] }]
                }

                if (sessionRecordingId === 'not_already_contained') {
                    return [200, { count: 2, results: allNotebooks.slice(2) }]
                }

                if (sessionRecordingId === 'very_slow') {
                    return res(ctx.delay('infinite'), ctx.status(200), ctx.json({ count: 0, results: [] }))
                }
            },
        },
    })

    return (
        // the button has its dropdown showing and so needs a container that will include the pop-over
        <div className={'min-h-100'}>
            <NotebookAddButton resource={props.resource} visible={props.visible} />
        </div>
    )
}

export const Default = Template.bind({})
Default.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: '123' } },
    visible: true,
}

export const ClosedPopoverState = Template.bind({})
ClosedPopoverState.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: '123' } },
    visible: false,
}

export const WithSlowNetworkResponse = Template.bind({})
WithSlowNetworkResponse.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'very_slow' } },
    visible: true,
}

export const WithSlowNetworkResponseClosedPopover = Template.bind({})
WithSlowNetworkResponseClosedPopover.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'very_slow' } },
    visible: false,
}

export const WithNoExistingContainingNotebooks = Template.bind({})
WithNoExistingContainingNotebooks.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'not_already_contained' } },
    visible: true,
}

export const WithNoNotebooks = Template.bind({})
WithNoNotebooks.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'there_are_no_notebooks' } },
    visible: true,
}
