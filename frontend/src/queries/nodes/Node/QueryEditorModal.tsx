import { LemonModal } from 'lib/components/LemonModal'
import { useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { IconEvent } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Node } from '~/queries/schema'

export interface QueryEditorModalProps {
    query: Node
    setQuery?: (query: Node) => void
}

export function QueryEditorModal({ query, setQuery }: QueryEditorModalProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <>
            <LemonButton tooltip="Edit Code" type="secondary" onClick={() => setOpen(true)}>
                <IconEvent />
            </LemonButton>
            <LemonModal isOpen={open} onClose={() => setOpen(false)} simple title={''} width={880}>
                <LemonModal.Content embedded>
                    <QueryEditor
                        query={JSON.stringify(query, null, 4)}
                        setQuery={setQuery ? (query) => setQuery(JSON.parse(query)) : undefined}
                    />
                </LemonModal.Content>
            </LemonModal>
        </>
    )
}
