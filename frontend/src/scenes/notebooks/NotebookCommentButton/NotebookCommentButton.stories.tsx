import { Meta, StoryFn } from '@storybook/react'
import { NotebookCommentButton } from 'scenes/notebooks/NotebookCommentButton/NotebookCommentButton'
import { useStorybookMocks } from '~/mocks/browser'

export default {
    title: 'Scenes-App/Notebooks/Components/Notebook Comment Button',
    component: NotebookCommentButton,
} as Meta<typeof NotebookCommentButton>

const Template: StoryFn<typeof NotebookCommentButton> = (props) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/notebooks/': (req, res, ctx) => {
                const contains = req.url.searchParams.get('contains')
                const sessionRecordingId = contains?.split(':')[1]
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
                getCurrentPlayerTime={() => 0}
                visible={true}
            />
        </div>
    )
}

export const Default = {
    render: Template,

    args: {
        sessionRecordingId: '123',
    },
}

export const WithSlowNetworkResponse = {
    render: Template,

    args: {
        sessionRecordingId: 'very_slow',
    },
}

export const WithNoExistingNotebooks = {
    render: Template,

    args: {
        sessionRecordingId: 'not_already_in_use',
    },
}
