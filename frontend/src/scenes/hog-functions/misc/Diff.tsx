import { DiffEditor } from '@monaco-editor/react'

import 'lib/monaco/monacoEnvironment'
import { initHogLanguage } from 'lib/monaco/languages/hog'
import monacoStylesheetUrl from 'lib/monaco/monacoStylesheet.css?url'
import { useStylesheet } from 'lib/utils/lazyStylesheet'

export interface DiffProps {
    before: string
    after: string
    language?: string
}

export function Diff({ before, after, language }: DiffProps): JSX.Element {
    if (!useStylesheet(monacoStylesheetUrl)) {
        return <div className="h-[300px]" />
    }
    return (
        <DiffEditor
            height="300px"
            original={before}
            modified={after}
            language={language ?? 'json'}
            onMount={(_, monaco) => {
                if (language === 'hog') {
                    initHogLanguage(monaco)
                }
            }}
            options={{
                lineNumbers: 'off',
                minimap: { enabled: false },
                folding: false,
                wordWrap: 'on',
                renderLineHighlight: 'none',
                scrollbar: { vertical: 'auto', horizontal: 'hidden' },
                overviewRulerBorder: false,
                hideCursorInOverviewRuler: true,
                overviewRulerLanes: 0,
                tabFocusMode: true,
                enableSplitViewResizing: false,
                renderSideBySide: false,
                readOnly: true,
            }}
        />
    )
}
