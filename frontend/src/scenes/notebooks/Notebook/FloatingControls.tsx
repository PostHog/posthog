import { FloatingMenu } from '@tiptap/react'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { IconCohort, IconPlus, IconQueryEditor, IconRecording, IconTableChart } from 'lib/lemon-ui/icons'
import { useCallback } from 'react'
import { isCurrentNodeEmpty } from './utils'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { NotebookNodeType } from '~/types'
import { examples } from '~/queries/examples'

export function FloatingControls(): JSX.Element | null {
    const { editor } = useValues(notebookLogic)
    const { insertPostHogNode } = useActions(notebookLogic)

    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    return editor ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left' }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            <LemonMenu
                items={[
                    {
                        title: (
                            <div className="flex items-center gap-1 border-b pb-1">
                                <LemonButton
                                    status="primary-alt"
                                    size="small"
                                    onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                                >
                                    H1
                                </LemonButton>
                                <LemonButton
                                    status="primary-alt"
                                    size="small"
                                    onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                                >
                                    H2
                                </LemonButton>
                                <LemonButton
                                    status="primary-alt"
                                    size="small"
                                    onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
                                >
                                    H3
                                </LemonButton>
                            </div>
                        ),
                        items: [
                            {
                                icon: <IconRecording />,
                                label: 'Session Replays',
                                onClick: () => {
                                    insertPostHogNode(NotebookNodeType.RecordingPlaylist)
                                },
                            },
                            {
                                icon: <IconTableChart />,
                                label: 'Events',
                                onClick: () => {
                                    insertPostHogNode(NotebookNodeType.Query, {
                                        query: examples['EventsTableFull'],
                                    })
                                },
                            },
                            {
                                icon: <IconQueryEditor />,
                                label: 'HoqQL',
                                onClick: () => {
                                    insertPostHogNode(NotebookNodeType.Query, {
                                        query: examples['HogQLTable'],
                                    })
                                },
                            },
                            {
                                icon: <IconCohort />,
                                label: 'Persons',
                                onClick: () => {
                                    insertPostHogNode(NotebookNodeType.Query, {
                                        query: examples['PersonsTableFull'],
                                    })
                                },
                            },
                        ],
                    },
                ]}
                tooltipPlacement={'right'}
                placement={'right-start'}
                actionable
            >
                <LemonButton size="small" icon={<IconPlus />} />
            </LemonMenu>
        </FloatingMenu>
    ) : null
}
