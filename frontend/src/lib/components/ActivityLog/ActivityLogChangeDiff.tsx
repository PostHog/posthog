import useSize from '@react-hook/size'
import { Suspense, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { ActivityChange } from './humanizeActivity'

const MonacoDiffEditor = lazyWithRetry(() => import('../MonacoDiffEditor'))

interface ActivityLogChangeDiffProps {
    field: string | undefined
    before: ActivityChange['before']
    after: ActivityChange['after']
}

export const ActivityLogChangeDiff = ({ field, before, after }: ActivityLogChangeDiffProps): JSX.Element => {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)
    return (
        <div ref={containerRef} className="flex flex-col space-y-2 w-full">
            {field ? <h2>{field}</h2> : null}
            <Suspense fallback={<Spinner className="text-2xl mx-auto my-4" />}>
                <MonacoDiffEditor
                    original={JSON.stringify(before, null, 2)}
                    modified={JSON.stringify(after, null, 2)}
                    language="json"
                    width={width}
                    options={{
                        renderOverviewRuler: false,
                        scrollBeyondLastLine: false,
                        hideUnchangedRegions: {
                            enabled: true,
                            contextLineCount: 3,
                            minimumLineCount: 3,
                            revealLineCount: 20,
                        },
                        diffAlgorithm: 'advanced',
                    }}
                />
            </Suspense>
        </div>
    )
}
