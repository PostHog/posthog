import { useState } from 'react'

import { IconCursorClick, IconMegaphone, IconMessage } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { ProductTourType } from '~/types'

type ModalStep = 'type-selection' | 'url-selection' | 'announcement-config'
type AnnouncementPresentation = 'modal' | 'banner'

const MODAL_TITLES: Record<ModalStep, string> = {
    'type-selection': 'What would you like to create?',
    'url-selection': 'Create a new product tour',
    'announcement-config': 'Create a new announcement',
}

const MODAL_DESCRIPTIONS: Partial<Record<ModalStep, string>> = {
    'url-selection': 'Select a URL to launch the toolbar and create your product tour',
}

export interface NewProductTourModalProps {
    isOpen: boolean
    onClose: () => void
    onCreateAnnouncement: (name: string) => void
    onCreateBanner: (name: string) => void
}

export function NewProductTourModal({
    isOpen,
    onClose,
    onCreateAnnouncement,
    onCreateBanner,
}: NewProductTourModalProps): JSX.Element {
    const [modalStep, setModalStep] = useState<ModalStep>('type-selection')
    const [presentation, setPresentation] = useState<AnnouncementPresentation>('modal')
    const [announcementName, setAnnouncementName] = useState('')

    const resetModal = (): void => {
        setModalStep('type-selection')
        setPresentation('modal')
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
            setModalStep('announcement-config')
        }
    }

    const handleCreate = (): void => {
        if (announcementName.trim()) {
            if (presentation === 'banner') {
                onCreateBanner(announcementName.trim())
            } else {
                onCreateAnnouncement(announcementName.trim())
            }
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
            ) : modalStep === 'announcement-config' ? (
                <AnnouncementConfigStep
                    presentation={presentation}
                    onPresentationChange={setPresentation}
                    name={announcementName}
                    onNameChange={setAnnouncementName}
                    onBack={resetModal}
                    onCreate={handleCreate}
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

function BannerIcon(): JSX.Element {
    return (
        <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="4" width="20" height="6" rx="1" stroke="currentColor" strokeWidth="2" />
            <rect x="2" y="14" width="20" height="6" rx="1" stroke="currentColor" strokeWidth="2" strokeOpacity="0.3" />
        </svg>
    )
}

function AnnouncementConfigStep({
    presentation,
    onPresentationChange,
    name,
    onNameChange,
    onBack,
    onCreate,
}: {
    presentation: AnnouncementPresentation
    onPresentationChange: (presentation: AnnouncementPresentation) => void
    name: string
    onNameChange: (name: string) => void
    onBack: () => void
    onCreate: () => void
}): JSX.Element {
    const placeholder =
        presentation === 'banner' ? 'e.g. New feature alert, Holiday sale' : 'e.g. New feature launch, Welcome message'

    return (
        <div className="space-y-6">
            <div>
                <LemonLabel className="mb-3">Style</LemonLabel>
                <LemonSegmentedButton
                    fullWidth
                    value={presentation}
                    onChange={(value) => onPresentationChange(value as AnnouncementPresentation)}
                    options={[
                        {
                            value: 'modal',
                            label: (
                                <span className="flex items-center gap-2">
                                    <IconMessage className="text-base" />
                                    Modal
                                </span>
                            ),
                        },
                        {
                            value: 'banner',
                            label: (
                                <span className="flex items-center gap-2">
                                    <BannerIcon />
                                    Banner
                                </span>
                            ),
                        },
                    ]}
                />
                <p className="text-muted text-xs mt-2">
                    {presentation === 'modal'
                        ? 'Popup with rich content, images, and custom positioning'
                        : 'Horizontal bar at top of page'}
                </p>
            </div>

            <div>
                <LemonLabel className="mb-2">Name</LemonLabel>
                <LemonInput
                    placeholder={placeholder}
                    value={name}
                    onChange={onNameChange}
                    autoFocus
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && name.trim()) {
                            onCreate()
                        }
                    }}
                />
            </div>

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
