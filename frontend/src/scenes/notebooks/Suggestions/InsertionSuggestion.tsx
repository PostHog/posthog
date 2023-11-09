import { NotebookEditor } from '~/types'
import { TipTapNode } from '../Notebook/types'

export type InsertionSuggestionViewProps = {
    previousNode: TipTapNode | null
    editor: NotebookEditor
}

interface InsertionSuggestionConfig {
    shouldShow: boolean | (({ previousNode }: { previousNode: TipTapNode | null }) => boolean)
    Component: (props: InsertionSuggestionViewProps) => JSX.Element
    onTab?: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: TipTapNode | null }) => void
}

export class InsertionSuggestion {
    dismissed = false
    shouldShow: boolean | (({ previousNode }: { previousNode: TipTapNode | null }) => boolean) = false
    onTab: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: TipTapNode | null }) => void =
        () => {}
    Component: (props: InsertionSuggestionViewProps) => JSX.Element

    constructor(config: InsertionSuggestionConfig) {
        this.shouldShow = config.shouldShow
        this.Component = config.Component

        if (config.onTab) {
            this.onTab = config.onTab
        }
    }

    static create(config: InsertionSuggestionConfig): InsertionSuggestion {
        return new InsertionSuggestion(config)
    }
}
