import useSize from '@react-hook/size'
import { useRef } from 'react'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

interface QueryDiffViewerProps {
    original: string
    modified: string
}

export function QueryDiffViewer({ original, modified }: QueryDiffViewerProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)
    return (
        <div ref={containerRef} className="flex flex-col space-y-2 w-full">
            <MonacoDiffEditor
                key="diff-viewer"
                original={original}
                modified={modified}
                language="hogQL"
                width={width}
                options={{
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    renderGutterMenu: false,
                    scrollbar: {
                        alwaysConsumeMouseWheel: false,
                    },
                }}
            />
        </div>
    )
}
