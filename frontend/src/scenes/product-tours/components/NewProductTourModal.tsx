import { useState } from 'react'

import { IconCursorClick, IconMegaphone } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { ProductTourType } from '~/types'

type ModalStep = 'type-selection' | 'url-selection' | 'announcement-name'

const MODAL_TITLES: Record<ModalStep, string> = {
    'type-selection': 'What would you like to create?',
    'url-selection': 'Create a new product tour',
    'announcement-name': 'Create a new announcement',
}

const MODAL_DESCRIPTIONS: Partial<Record<ModalStep, string>> = {
    'url-selection': 'Select a URL to launch the toolbar and create your product tour',
}

export interface NewProductTourModalProps {
    isOpen: boolean
    onClose: () => void
    onCreateAnnouncement: (name: string) => void
}

export function NewProductTourModal({ isOpen, onClose, onCreateAnnouncement }: NewProductTourModalProps): JSX.Element {
    const [modalStep, setModalStep] = useState<ModalStep>('type-selection')
    const [announcementName, setAnnouncementName] = useState('')

    const resetModal = (): void => {
        setModalStep('type-selection')
        setAnnouncementName('')
    }

    const handleClose = (): void => {
        onClose()
        resetModal()
    }

    const handleTypeSelect = (type: ProductTourType): void => {
        if (type === 'tour') {
            setModalStep('url-selection')
        } else {
            setModalStep('announcement-name')
        }
    }

    const handleCreateAnnouncement = (): void => {
        if (announcementName.trim()) {
            onCreateAnnouncement(announcementName.trim())
            handleClose()
        }
    }

    return (
        <LemonModal
            title={MODAL_TITLES[modalStep]}
            description={MODAL_DESCRIPTIONS[modalStep]}
            isOpen={isOpen}
            onClose={handleClose}
            width={600}
        >
            {modalStep === 'type-selection' ? (
                <TypeSelectionStep onSelect={handleTypeSelect} />
            ) : modalStep === 'announcement-name' ? (
                <AnnouncementNameStep
                    name={announcementName}
                    onChange={setAnnouncementName}
                    onBack={resetModal}
                    onCreate={handleCreateAnnouncement}
                />
            ) : (
                <UrlSelectionStep onBack={resetModal} />
            )}
        </LemonModal>
    )
}

function TypeSelectionStep({ onSelect }: { onSelect: (type: ProductTourType) => void }): JSX.Element {
    return (
        <div className="flex gap-3 mt-2">
            <button
                type="button"
                onClick={() => onSelect('tour')}
                className="flex-1 flex flex-col items-center gap-3 p-6 rounded-lg border border-border hover:border-primary hover:bg-fill-button-tertiary-hover cursor-pointer transition-colors text-left"
            >
                <IconCursorClick className="text-3xl text-muted" />
                <div>
                    <div className="font-semibold mb-1">Product tour</div>
                    <div className="text-muted text-sm">
                        Multi-step walkthrough that guides users through your product
                    </div>
                </div>
            </button>
            <button
                type="button"
                onClick={() => onSelect('announcement')}
                className="flex-1 flex flex-col items-center gap-3 p-6 rounded-lg border border-border hover:border-primary hover:bg-fill-button-tertiary-hover cursor-pointer transition-colors text-left"
            >
                <IconMegaphone className="text-3xl text-muted" />
                <div>
                    <div className="font-semibold mb-1">Announcement</div>
                    <div className="text-muted text-sm">
                        Single popup to announce a feature, share news, or display a message
                    </div>
                </div>
            </button>
        </div>
    )
}

function AnnouncementNameStep({
    name,
    onChange,
    onBack,
    onCreate,
}: {
    name: string
    onChange: (name: string) => void
    onBack: () => void
    onCreate: () => void
}): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonLabel className="mb-2">Announcement title</LemonLabel>
            <LemonInput
                placeholder="e.g. New feature launch, Welcome message"
                value={name}
                onChange={onChange}
                autoFocus
                onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        onCreate()
                    }
                }}
            />
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={onBack}>
                    Back
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={onCreate}
                    disabledReason={!name.trim() ? 'Enter a name' : undefined}
                >
                    Create
                </LemonButton>
            </div>
        </div>
    )
}

function UrlSelectionStep({ onBack }: { onBack: () => void }): JSX.Element {
    return (
        <div className="mt-4 flex flex-col space-y-4">
            <AuthorizedUrlList
                type={AuthorizedUrlListType.TOOLBAR_URLS}
                addText="Add authorized URL"
                productTourId="new"
            />
            <div>
                <LemonButton type="secondary" onClick={onBack}>
                    &larr; Back
                </LemonButton>
            </div>
        </div>
    )
}
