import { IconGear } from '@posthog/icons'
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Separator } from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { defaultSurveyAppearance } from 'scenes/surveys/constants'
import { CommonProps } from 'scenes/surveys/survey-appearance/types'

import { AvailableFeature } from '~/types'

import { QuillSurveyColorsAppearance } from './QuillSurveyColorsAppearance'
import { QuillSurveyContainerAppearance } from './QuillSurveyContainerAppearance'
import { QuillSurveyPreview } from './QuillSurveyPreview'

export function QuillSurveyAppearanceModal({
    survey,
    onAppearanceChange,
    validationErrors,
    hasRatingButtons,
    hasPlaceholderText,
    selectedPageIndex,
    setSelectedPageIndex,
    disabledReason,
    isOpen,
    surveysStylingAvailable,
    onOpen,
    onClose,
}: CommonProps & {
    isOpen: boolean
    surveysStylingAvailable: boolean
    onOpen: () => void
    onClose: () => void
}): JSX.Element {
    return (
        <>
            <Button variant="outline" className="w-full" onClick={onOpen} disabledReason={disabledReason}>
                <IconGear />
                Full-screen survey editor
            </Button>
            <Dialog
                open={isOpen}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        onClose()
                    }
                }}
            >
                <DialogContent size="full" className="flex flex-col">
                    <DialogHeader>
                        <DialogTitle>Customize Survey Appearance</DialogTitle>
                    </DialogHeader>
                    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-4 md:flex-row">
                        <div className="flex flex-1 flex-col gap-4 overflow-y-auto scroll-mask-y-4 scroll-py-4 pe-1">
                            {!surveysStylingAvailable && (
                                <PayGateMini
                                    feature={AvailableFeature.SURVEYS_STYLING}
                                    featureDetail="survey-appearance-modal"
                                >
                                    <></>
                                </PayGateMini>
                            )}
                            <QuillSurveyContainerAppearance
                                appearance={survey.appearance || defaultSurveyAppearance}
                                onAppearanceChange={onAppearanceChange}
                                validationErrors={validationErrors}
                                surveyType={survey.type}
                                disabledReason={disabledReason}
                            />
                            <Separator />
                            <QuillSurveyColorsAppearance
                                appearance={survey.appearance || defaultSurveyAppearance}
                                onAppearanceChange={onAppearanceChange}
                                validationErrors={validationErrors}
                                customizeRatingButtons={hasRatingButtons}
                                customizePlaceholderText={hasPlaceholderText}
                                disabledReason={disabledReason}
                            />
                        </div>
                        <QuillSurveyPreview
                            survey={survey}
                            selectedPageIndex={selectedPageIndex}
                            setSelectedPageIndex={setSelectedPageIndex}
                        />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={onClose}>
                            Close
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
