import { Node } from '@tiptap/pm/model'

export type InsertionSuggestionViewProps = {
    previousNode?: Node | null
}

interface InsertionSuggestionConfig {
    Component: (props: InsertionSuggestionViewProps) => JSX.Element
    shouldShow: boolean | (({ previousNode }: { previousNode: Node }) => boolean)
    onTab?: ({ previousNode }: { previousNode: Node | null }) => void
}

export class InsertionSuggestion {
    dismissed = false
    shouldShow: boolean | (({ previousNode }: { previousNode: Node }) => boolean) = false
    onTab: ({ previousNode }: { previousNode: Node | null }) => void = () => {}
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
