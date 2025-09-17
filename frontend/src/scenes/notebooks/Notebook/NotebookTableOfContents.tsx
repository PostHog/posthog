import { useActions, useValues } from 'kea'

import { LemonWidget, Link } from '@posthog/lemon-ui'

import { notebookLogic } from './notebookLogic'
import { notebookSettingsLogic } from './notebookSettingsLogic'

export function NotebookTableOfContents(): JSX.Element {
    const { editor, tableOfContents } = useValues(notebookLogic)
    const { setShowTableOfContents } = useActions(notebookSettingsLogic)

    const onItemClick = (id: string): void => {
        const item = tableOfContents.find((i) => i.id === id)

        if (item && editor) {
            editor.scrollToPosition(item.pos)
        }
    }

    return (
        <LemonWidget title="Table of Contents" onClose={() => setShowTableOfContents(false)}>
            {tableOfContents.length === 0 ? (
                <div>Start editing your Notebook to see the outline.</div>
            ) : (
                tableOfContents.map((item) => (
                    <div key={item.id} style={{ paddingLeft: 12 * item.level }}>
                        <Link onClick={() => onItemClick(item.id)} subtle>
                            {item.textContent}
                        </Link>
                    </div>
                ))
            )}
        </LemonWidget>
    )
}
