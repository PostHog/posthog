import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function PreviewingCustomCssModal(): JSX.Element | null {
    const [editingInline, setEditingInline] = useState<boolean>(false)

    const { previewingCustomCss } = useValues(themeLogic)
    const { saveCustomCss, setPreviewingCustomCss } = useActions(themeLogic)
    const {
        location: { pathname },
    } = useValues(router)

    const isCustomCSSPage = pathname.includes(urls.customCss())
    const open = !isCustomCSSPage && !!previewingCustomCss

    return (
        <dialog
            open={open}
            className="absolute bottom-0 mb-4 px-3 py-2 space-y-2 border rounded shadow min-w-[34rem] z-[var(--z-popover)]"
        >
            {editingInline && (
                <CodeEditor
                    className="border"
                    language="css"
                    value={previewingCustomCss || ''}
                    onChange={(v) => setPreviewingCustomCss(v ?? null)}
                    height={600}
                    options={{
                        minimap: { enabled: false },
                    }}
                />
            )}
            <div className="flex justify-between items-center space-x-2">
                <h3 className="mb-0">Custom CSS</h3>
                <div className="flex space-x-2">
                    <LemonButton type="secondary" onClick={() => setEditingInline(!editingInline)}>
                        {editingInline ? 'Minimize editor' : 'Edit'}
                    </LemonButton>
                    <LemonButton type="primary" onClick={saveCustomCss}>
                        Save and close
                    </LemonButton>
                </div>
            </div>
        </dialog>
    )
}
