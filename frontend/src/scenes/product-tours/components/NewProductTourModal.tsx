import classNames from 'classnames'
import { useState } from 'react'

import { IconCursorClick, IconMegaphone } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

type TourType = 'tour' | 'announcement' | 'banner' | undefined

export interface NewProductTourModalProps {
    isOpen: boolean
    onClose: () => void
    onCreateAnnouncement: (name: string) => void
    onCreateBanner: (name: string) => void
    onCreateTour: (name: string) => void
    existingTourNames: Set<string>
}

export function NewProductTourModal({
    isOpen,
    onClose,
    onCreateAnnouncement,
    onCreateBanner,
    onCreateTour,
    existingTourNames,
}: NewProductTourModalProps): JSX.Element {
    const [tourType, setTourType] = useState<TourType>()
    const [tourName, setTourName] = useState<string | undefined>()
    const [tourNameError, setTourNameError] = useState<string | undefined>()

    const resetModal = (): void => {
        setTourName(undefined)
        setTourType(undefined)
        setTourNameError(undefined)
    }

    const handleClose = (): void => {
        onClose()
        resetModal()
    }

    const handleCreate = (): void => {
        const name = tourName?.trim()
        if (!name) {
            checkTourNameError(tourName ?? '')
            return
        }
        if (tourNameError) {
            return
        }

        if (tourType === 'tour') {
            onCreateTour(name)
        } else if (tourType === 'announcement') {
            onCreateAnnouncement(name)
        } else if (tourType === 'banner') {
            onCreateBanner(name)
        }
        handleClose()
    }

    const checkTourNameError = (name: string): void => {
        if (!name.trim()) {
            setTourNameError('Please enter name for your tour')
        } else if (existingTourNames.has(name.trim())) {
            setTourNameError('A tour with this name already exists')
        } else {
            setTourNameError(undefined)
        }
    }

    return (
        <LemonModal title="What would you like to create?" isOpen={isOpen} onClose={handleClose} width={800}>
            <div className="flex flex-col gap-4">
                <div className="flex gap-3 mt-2">
                    <TourTypeButton
                        icon={IconCursorClick}
                        title="Product tour"
                        description="Multi-step walkthrough that guides users through your product"
                        onClick={() => setTourType('tour')}
                        active={tourType === 'tour'}
                    />
                    <TourTypeButton
                        icon={IconMegaphone}
                        title="Announcement"
                        description="Single popup or element tooltip to announce a feature or share a message"
                        onClick={() => setTourType('announcement')}
                        active={tourType === 'announcement'}
                    />
                    <TourTypeButton
                        icon={BannerIcon}
                        title="Banner"
                        description="Display a message in a banner at the top of your page"
                        onClick={() => setTourType('banner')}
                        active={tourType === 'banner'}
                    />
                </div>

                {tourType && (
                    <>
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Name</LemonLabel>
                            <LemonInput
                                placeholder={`Enter a name for your ${tourType}`}
                                value={tourName}
                                onChange={(val) => {
                                    setTourName(val)
                                    checkTourNameError(val)
                                }}
                                autoFocus
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        handleCreate()
                                    }
                                }}
                            />
                            {tourNameError ? (
                                <p className="text-danger text-xs mt-1">{tourNameError}</p>
                            ) : (
                                <p className="text-muted text-xs mt-1">
                                    This name is just for you - it will not be shown to your users.
                                </p>
                            )}
                        </div>

                        <div className="flex justify-end">
                            <LemonButton type="primary" onClick={handleCreate} disabledReason={tourNameError}>
                                Create
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}

function BannerIcon({ className }: { className?: string }): JSX.Element {
    return (
        <svg
            className={className}
            width="1em"
            height="1em"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <rect x="2" y="4" width="20" height="6" rx="1" stroke="currentColor" strokeWidth="2" />
            <rect x="2" y="14" width="20" height="6" rx="1" stroke="currentColor" strokeWidth="2" strokeOpacity="0.3" />
        </svg>
    )
}

function TourTypeButton({
    icon: Icon,
    title,
    description,
    active,
    onClick,
}: {
    icon: React.ComponentType<{ className?: string }>
    title: string
    description: string
    active: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={classNames(
                'group flex-1 flex flex-col items-center gap-3 p-6 rounded-lg border-2 cursor-pointer transition-colors text-left',
                active ? 'border-accent' : 'border-border hover:border-accent/70'
            )}
        >
            <Icon
                className={classNames(
                    'text-3xl transition-colors',
                    active ? 'text-accent' : 'text-muted group-hover:text-accent/70'
                )}
            />
            <div className="text-center">
                <div className="font-semibold mb-1">{title}</div>
                <div className="text-muted text-sm">{description}</div>
            </div>
        </button>
    )
}
