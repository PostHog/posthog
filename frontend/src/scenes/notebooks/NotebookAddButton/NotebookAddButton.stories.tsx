import { ComponentMeta, ComponentStory } from '@storybook/react'
import { NotebookAddButton } from 'scenes/notebooks/NotebookAddButton/NotebookAddButton'
import { useStorybookMocks } from '~/mocks/browser'
import { NotebookNodeType } from '~/types'

export default {
    title: 'Scenes-App/Notebooks/Components/Notebook Comment Button',
    component: NotebookAddButton,
} as ComponentMeta<typeof NotebookAddButton>

const Template: ComponentStory<typeof NotebookAddButton> = (props) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/notebooks/': (req, res, ctx) => {
                const contains = req.url.searchParams.get('contains')
                const sessionRecordingId = contains?.split(':')[1]
                const allNotebooks = [
                    {
                        title: 'my amazing notebook',
                        short_id: 'abc',
                    },
                    { title: 'and another amazing notebook', short_id: 'def' },
                    { title: 'an empty notebook', short_id: 'ghi' },
                ]

                const unfiltered = contains == null && sessionRecordingId === undefined
                if (unfiltered) {
                    return [200, allNotebooks]
                }

                if (sessionRecordingId === 'there_are_no_notebooks') {
                    return [200, []]
                }

                if (sessionRecordingId === 'not_already_contained') {
                    return [200, allNotebooks.slice(2)]
                }

                if (sessionRecordingId === 'very_slow') {
                    return res(
                        ctx.delay('infinite'),
                        ctx.status(200),
                        ctx.json({
                            results: [],
                        })
                    )
                }
            },
        },
    })

    return (
        // the button has its dropdown showing and so needs a container that will include the pop-over
        <div className={'min-h-100'}>
            <NotebookAddButton resource={props.resource} />
        </div>
    )
}

export const Default = Template.bind({})
Default.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: '123' } },
}

export const WithSlowNetworkResponse = Template.bind({})
WithSlowNetworkResponse.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'very_slow' } },
}

export const WithNoExistingContainingNotebooks = Template.bind({})
WithNoExistingContainingNotebooks.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'not_already_contained' } },
}

export const WithNoNotebooks = Template.bind({})
WithNoExistingContainingNotebooks.args = {
    resource: { type: NotebookNodeType.Recording, attrs: { id: 'there_are_no_notebooks' } },
}
