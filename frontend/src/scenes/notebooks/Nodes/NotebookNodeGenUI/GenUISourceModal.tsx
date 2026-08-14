import { BuiltLogic, useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { notebookNodeGenUILogicType } from './notebookNodeGenUILogic'

export function GenUISourceModal({ logic }: { logic: BuiltLogic<notebookNodeGenUILogicType> }): JSX.Element {
    const { source, sourceLoading, sourceModalOpen } = useValues(logic)
    const { closeSource } = useActions(logic)

    return (
        <LemonModal
            isOpen={sourceModalOpen}
            onClose={closeSource}
            title="Visualization source"
            description="Generated React code for the current visualization version."
            width="min(960px, 90vw)"
        >
            {sourceLoading ? (
                <LemonSkeleton className="h-[60vh] w-full" />
            ) : source ? (
                <CodeEditor
                    className="h-[60vh] overflow-hidden rounded border"
                    language="typescript"
                    value={source.source}
                    height="60vh"
                    options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        wordWrap: 'on',
                    }}
                />
            ) : (
                <div className="py-8 text-center text-muted">The visualization source is unavailable. Try again.</div>
            )}
        </LemonModal>
    )
}
