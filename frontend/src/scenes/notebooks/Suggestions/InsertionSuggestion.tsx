import { Node, NotebookEditor } from '../Notebook/utils'

export type InsertionSuggestionViewProps = {
    previousNode: Node | null
    editor: NotebookEditor
}

interface InsertionSuggestionConfig {
    shouldShow: boolean | (({ previousNode }: { previousNode: Node | null }) => boolean)
    Component: (props: InsertionSuggestionViewProps) => JSX.Element
    onTab?: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: Node | null }) => void
}

export class InsertionSuggestion {
    dismissed = false
    shouldShow: boolean | (({ previousNode }: { previousNode: Node | null }) => boolean) = false
    onTab: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: Node | null }) => void = () => {}
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
