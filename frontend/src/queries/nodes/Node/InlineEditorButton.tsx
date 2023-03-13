import { useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { IconEvent } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Node } from '~/queries/schema'
import { Drawer } from 'lib/components/Drawer'
import { urls } from 'scenes/urls'

export interface InlineEditorButtonProps {
    query: Node
    setQuery?: (query: Node) => void
    linkToQueryEditor?: boolean
}

export function InlineEditorButton({
    query,
    setQuery,
    linkToQueryEditor = true,
}: InlineEditorButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <>
            <LemonButton tooltip="Edit code" type="secondary" onClick={() => setOpen(true)}>
                <IconEvent />
            </LemonButton>
            <Drawer
                visible={open}
                onClose={() => setOpen(false)}
                width="60vw"
                title={
                    linkToQueryEditor ? (
                        <>
                            <LemonButton to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
                                Open in Query Builder
                            </LemonButton>
                        </>
                    ) : undefined
                }
            >
                <QueryEditor
                    query={JSON.stringify(query, null, 4)}
                    setQuery={setQuery ? (query) => setQuery(JSON.parse(query)) : undefined}
                />
            </Drawer>
        </>
    )
}
