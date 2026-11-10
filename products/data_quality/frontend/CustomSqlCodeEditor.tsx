import { useActions, useValues } from 'kea'
import type { MutableRefObject } from 'react'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import type { CodeEditorInstance } from './customSqlEditor'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'

export interface CustomSqlCodeEditorProps {
    value: string | undefined
    onChange: (query: string) => void
    editorRef: MutableRefObject<CodeEditorInstance | null>
}

export function CustomSqlCodeEditor({ value, onChange, editorRef }: CustomSqlCodeEditorProps): JSX.Element {
    const { customSqlQueryKey, customSqlSourceQuery, isMetricSubject } = useValues(dataQualityCheckEditorLogic)
    const { runCustomSqlPreview, setCustomSqlEditorError, setCustomSqlValidationLoading } =
        useActions(dataQualityCheckEditorLogic)

    return (
        <CodeEditorResizeable
            language="hogQL"
            value={value ?? ''}
            onChange={(query) => onChange(query ?? '')}
            queryKey={customSqlQueryKey}
            sourceQuery={customSqlSourceQuery}
            metadataQuery={isMetricSubject ? '' : undefined}
            onError={isMetricSubject ? undefined : setCustomSqlEditorError}
            onMetadataLoading={isMetricSubject ? undefined : setCustomSqlValidationLoading}
            onPressCmdEnter={isMetricSubject ? undefined : () => runCustomSqlPreview(undefined)}
            onMount={(editor) => {
                editorRef.current = editor
            }}
            autoFocus
            minHeight="8rem"
            maxHeight="40vh"
        />
    )
}
