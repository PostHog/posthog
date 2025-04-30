import { FolderSelect } from 'lib/components/FolderSelect/FolderSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useState } from 'react'

import { FileSystemEntry } from '~/queries/schema/schema-general'

interface MoveFilesModalProps {
    items: FileSystemEntry[]
    handleMove: (path: string) => void
    closeModal: () => void
}

export function MoveFilesModal({ items, handleMove, closeModal }: MoveFilesModalProps): JSX.Element {
    const [folderDestination, setFolderDestination] = useState<string>('')

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={true}
            title="Select a folder to move to"
            description={`You are moving ${items.length} item${items.length === 1 ? '' : 's'} to ${
                folderDestination || 'Project root'
            }`}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="primary" onClick={() => handleMove(folderDestination)}>
                        Move to {folderDestination || 'Project root'}
                    </LemonButton>
                </>
            }
        >
            <div className="w-192 max-w-full">
                <FolderSelect className="h-[60vh] min-h-[200px]" onChange={setFolderDestination} />
            </div>
        </LemonModal>
    )
}
