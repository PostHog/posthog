import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { SceneExport } from 'scenes/sceneTypes'

import { hogReplLogic, ReplChunk as ReplChunkType } from './hogReplLogic'

interface ReplChunkProps {
    chunk: ReplChunkType
    editFromHere: () => void
}
export function ReplChunk({
    chunk: { code, result, print, error, status },
    editFromHere,
}: ReplChunkProps): JSX.Element {
    return (
        <div className="pb-2 border-b border-gray-300">
            <LemonButton size="small" type="secondary" className="float-right" onClick={editFromHere}>
                📝
            </LemonButton>
            <div className="flex items-start">
                <span
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color: 'blue' }}
                >
                    {'>'}
                </span>
                <div className="flex-1 whitespace-pre-wrap ml-2">{code}</div>
            </div>
            {status === 'pending' && (
                <div className="flex items-center ml-4 mt-2">
                    <svg
                        className="animate-spin h-5 w-5 text-gray-500 mr-2"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                    >
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                </div>
            )}
            {print ? (
                <div className="flex items-start mt-2">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: 'green' }}
                    >
                        #
                    </span>
                    <div className="flex-1 whitespace-pre-wrap ml-2">{print}</div>
                </div>
            ) : null}
            {status === 'success' && (
                <div className="flex items-start mt-2">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: 'green' }}
                    >
                        {'<'}
                    </span>
                    <div className="flex-1 whitespace-pre-wrap ml-2">{String(result)}</div>
                </div>
            )}
            {status === 'error' && (
                <div className="flex items-start mt-2">
                    <span className="text-danger">!</span>
                    <div className="flex-1 whitespace-pre-wrap ml-2 text-danger">{error}</div>
                </div>
            )}
        </div>
    )
}

export function HogRepl(): JSX.Element {
    const { replChunks, currentCode, lastLocalGlobals } = useValues(hogReplLogic)
    const { runCurrentCode, setCurrentCode, editFromHere } = useActions(hogReplLogic)

    return (
        <div className="p-4 bg-white text-black font-mono">
            <div className="space-y-4">
                {replChunks.map((chunk, index) => (
                    <ReplChunk chunk={chunk} key={index} editFromHere={() => editFromHere(index)} />
                ))}
                <div className="flex items-start">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: 'blue' }}
                    >
                        {'>'}
                    </span>
                    <div
                        className="w-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ marginLeft: -10, marginTop: -7, marginRight: -5, marginBottom: -5 }}
                    >
                        <CodeEditorInline
                            language="hog"
                            embedded
                            className="flex-1 bg-transparent focus:outline-none resize-none ml-2 p-0"
                            value={currentCode}
                            onChange={(value) => setCurrentCode(value ?? '')}
                            onPressCmdEnter={runCurrentCode}
                            options={{ fontSize: 14, padding: { top: 0, bottom: 0 } }}
                            globals={lastLocalGlobals}
                            autoFocus
                        />
                    </div>
                    <LemonButton size="small" type="primary" onClick={runCurrentCode}>
                        ⌘⏎
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: HogRepl,
    logic: hogReplLogic,
}
