import { ComponentMeta, ComponentStory } from '@storybook/react'
import { NotebookCommentButton } from 'scenes/notebooks/NotebookCommentButton/NotebookCommentButton'
import { useStorybookMocks } from '~/mocks/browser'

export default {
    title: 'Scenes-App/Notebooks/Components/Notebook Comment Button',
    component: NotebookCommentButton,
} as ComponentMeta<typeof NotebookCommentButton>

const Template: ComponentStory<typeof NotebookCommentButton> = (props) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/notebooks/': (req, res, ctx) => {
                const sessionRecordingId = req.url.searchParams.get('has_recordings')
                return res(
                    ctx.delay(sessionRecordingId === 'very_slow' ? 'infinite' : 100),
                    ctx.status(200),
                    ctx.json({
                        results:
                            sessionRecordingId === '123'
                                ? [
                                      {
                                          title: 'my amazing notebook',
                                      },
                                      { title: 'and another amazing notebook' },
                                  ]
                                : [],
                    })
                )
            },
        },
    })

    return (
        // the button has its dropdown showing and so needs a container that will include the pop-over
        <div className={'min-h-50'}>
            <NotebookCommentButton
                sessionRecordingId={props.sessionRecordingId}
                onCommentInNewNotebook={() => {}}
                onCommentInExistingNotebook={() => {}}
                visible={true}
            />
        </div>
    )
}

export const Default = Template.bind({})
Default.args = {
    sessionRecordingId: '123',
}

export const WithSlowNetworkResponse = Template.bind({})
WithSlowNetworkResponse.args = {
    sessionRecordingId: 'very_slow',
}

export const WithNoExistingNotebooks = Template.bind({})
WithNoExistingNotebooks.args = {
    sessionRecordingId: 'not_already_in_use',
}
