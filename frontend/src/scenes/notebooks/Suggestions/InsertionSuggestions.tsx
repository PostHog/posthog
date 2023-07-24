import { Editor as TTEditor } from '@tiptap/core'
import { useCallback } from 'react'
import { isCurrentNodeEmpty } from '../Notebook/utils'
import { FloatingMenu } from '@tiptap/react'
import { useValues } from 'kea'
import { insertionSuggestionsLogic } from './insertionSuggestionsLogic'

export function InsertionSuggestions({ editor }: { editor: TTEditor }): JSX.Element | null {
    const { activeSuggestion } = useValues(insertionSuggestionsLogic({ editor }))

    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    console.log('re-renders from component')

    return editor ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left' }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            {activeSuggestion && <activeSuggestion.Component />}
        </FloatingMenu>
    ) : null
}

// export const InsertionSuggestionsExtension = Extension.create({
//     addKeyboardShortcuts() {
//         return {
//             Enter: ({}) => {
//                 console.log('Enter pressed')
//                 return false
//             },
//             Tab: ({}) => {
//                 console.log('Tab pressed')
//                 return false
//             },
//             Esc: ({}) => {
//                 console.log('Esc pressed')
//                 return false
//             },
//         }
//     },
// })
