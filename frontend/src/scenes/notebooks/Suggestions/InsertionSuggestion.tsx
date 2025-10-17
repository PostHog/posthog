import { RichContentEditorType, RichContentNode } from 'lib/components/RichContentEditor/types'

export type InsertionSuggestionViewProps = {
    previousNode: RichContentNode | null
    editor: RichContentEditorType
}

interface InsertionSuggestionConfig {
    shouldShow: boolean | (({ previousNode }: { previousNode: RichContentNode | null }) => boolean)
    Component: (props: InsertionSuggestionViewProps) => JSX.Element
    onTab?: ({
        editor,
        previousNode,
    }: {
        editor: RichContentEditorType | null
        previousNode: RichContentNode | null
    }) => void
}

export class InsertionSuggestion {
    dismissed = false
    shouldShow: boolean | (({ previousNode }: { previousNode: RichContentNode | null }) => boolean) = false
    onTab: ({
        editor,
        previousNode,
    }: {
        editor: RichContentEditorType | null
        previousNode: RichContentNode | null
    }) => void = () => {}
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
