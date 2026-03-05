import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

export function NodeDetailQuery({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const logicProps = { id }
    const { savedQuery } = useValues(nodeDetailSceneLogic(logicProps))
    const { openQueryModal } = useActions(nodeDetailSceneLogic(logicProps))

    const query = savedQuery?.query?.query

    if (!query) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-2">
            <h3 className="text-base font-semibold mb-0">Query</h3>
            <div className="relative border rounded overflow-hidden" style={{ height: 200 }}>
                <CodeEditor
                    language="hogQL"
                    value={query}
                    options={{
                        readOnly: true,
                        readOnlyMessage: { value: 'Open in SQL editor to edit this query' },
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        lineNumbers: 'off',
                        folding: false,
                        wordWrap: 'on',
                        renderLineHighlight: 'none',
                        overviewRulerLanes: 0,
                        hideCursorInOverviewRuler: true,
                        overviewRulerBorder: false,
                        scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                    }}
                    height="100%"
                />
                <div className="absolute top-2 right-2 z-10">
                    <LemonButton size="small" type="secondary" icon={<IconPencil />} onClick={openQueryModal} tooltip="Edit in SQL editor" />
                </div>
            </div>
        </div>
    )
}
