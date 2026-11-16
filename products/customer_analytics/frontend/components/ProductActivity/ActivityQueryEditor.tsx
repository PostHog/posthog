import { Suspense } from 'react'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { NodeKind, type HogQLQuery } from '~/queries/schema/schema-general'

const CodeEditor = lazyWithRetry(async () => ({ default: (await import('lib/monaco/CodeEditor')).CodeEditor }))

export function ActivityQueryEditor({
    queryKey,
    query,
    bindings,
    helpText,
    scopeWarning,
    onChange,
    onRun,
}: {
    queryKey: string
    query: string
    bindings: Pick<HogQLQuery, 'values' | 'filters'>
    helpText: string
    scopeWarning?: string | null
    onChange: (query: string) => void
    onRun: () => void
}): JSX.Element {
    return (
        <>
            <p className="text-secondary mb-0">{helpText}</p>
            {scopeWarning && <LemonBanner type="warning">{scopeWarning}</LemonBanner>}
            <Suspense fallback={<Spinner />}>
                <CodeEditor
                    queryKey={queryKey}
                    language="hogQL"
                    height={200}
                    sourceQuery={{ kind: NodeKind.HogQLQuery, query, ...bindings }}
                    globals={bindings.values ?? undefined}
                    value={query}
                    onChange={(value) => onChange(value ?? '')}
                    onPressCmdEnter={onRun}
                    options={{
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                    }}
                />
            </Suspense>
        </>
    )
}
