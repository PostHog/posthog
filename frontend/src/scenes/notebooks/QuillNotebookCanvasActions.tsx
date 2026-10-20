import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { loadNotebookFromJSON } from './loadNotebookFromJSON'
import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'

export function QuillNotebookCanvasActions({ logicProps }: { logicProps: NotebookLogicProps }): JSX.Element {
    const { duplicateNotebook, exportJSON, setLocalContent } = useActions(notebookLogic(logicProps))

    return (
        <>
            <DropdownMenu>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={<DropdownMenuTrigger render={<Button size="icon" aria-label="More actions" />} />}
                    >
                        <IconEllipsis />
                    </TooltipTrigger>
                    <TooltipContent>More actions</TooltipContent>
                </Tooltip>
                <DropdownMenuContent align="end" className="min-w-40">
                    <DropdownMenuItem onClick={() => setLocalContent({ type: 'doc', content: [] })}>
                        Clear canvas
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => exportJSON()}>Export as JSON</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => loadNotebookFromJSON(setLocalContent)}>
                        Load from JSON
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <Button
                variant="outline"
                onClick={() => {
                    void copyToClipboard(window.location.href, 'Canvas URL')
                }}
            >
                Share
            </Button>
            <Button variant="primary" onClick={duplicateNotebook}>
                Save as Notebook
            </Button>
        </>
    )
}
