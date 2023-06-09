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
            tippyOptions={{ duration: 100 }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            <LemonMenu
                items={[
                    {
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
                // sameWidth={dropdownMatchSelectWidth}
                placement={'right-start'}
                actionable
                // className={menu?.className}
                // maxContentWidth={dropdownMaxContentWidth}
                // activeItemIndex={items
                //     .flatMap((i) => (isLemonMenuSection(i) ? i.items.filter(Boolean) : i))
                //     .findIndex((i) => (i as LemonMenuItem).active)}
                // closeParentPopoverOnClickInside={menu?.closeParentPopoverOnClickInside}
            >
                <LemonButton size="small" icon={<IconPlus />} />
            </LemonMenu>
        </FloatingMenu>
    ) : null
}
