import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSelect, LemonSwitch, LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { defaultSurveyAppearance } from 'scenes/surveys/constants'
import {
    SurveyColorsAppearance,
    SurveyContainerAppearance,
} from 'scenes/surveys/survey-appearance/SurveyAppearanceSections'
import { CommonProps } from 'scenes/surveys/survey-appearance/types'

import { AvailableFeature, SurveyQuestionBranchingType, SurveyType } from '~/types'

import { SurveyAppearancePreview } from '../SurveyAppearancePreview'
import { surveysLogic } from '../surveysLogic'

type PreviewScreenSize = 'mobile' | 'tablet' | 'desktop'

const screenDimensions: Record<PreviewScreenSize, { width: string; height: string; scale?: number }> = {
    mobile: { width: '375px', height: '667px' },
    tablet: { width: '768px', height: '1024px' },
    desktop: { width: '100%', height: '100%' },
}

function SurveyPreview({
    selectedPageIndex,
    setSelectedPageIndex,
    survey,
}: Pick<CommonProps, 'selectedPageIndex' | 'setSelectedPageIndex' | 'survey'>): JSX.Element {
    const [activeScreenSize, setActiveScreenSize] = useState<PreviewScreenSize>('desktop')
    const [surveyPreviewBackground, setSurveyPreviewBackground] = useState<'light' | 'dark'>('light')

    const currentDimensions = screenDimensions[activeScreenSize]
    return (
        <div className="flex flex-[1.5] flex-col items-center justify-start gap-2 overflow-hidden rounded">
            <LemonTabs
                activeKey={activeScreenSize}
                onChange={(key) => setActiveScreenSize(key as PreviewScreenSize)}
                tabs={[
                    { key: 'desktop', label: 'Desktop Web' },
                    { key: 'tablet', label: 'Tablet Web' },
                    { key: 'mobile', label: 'Mobile Web' },
                ]}
                barClassName="mb-0"
            />
            <div className="flex min-w-full flex-col gap-2 md:flex-row md:items-center md:justify-between">
                {setSelectedPageIndex && (
                    <LemonField.Pure
                        label="Current question"
                        className="max-w-full gap-1 md:max-w-sm"
                        htmlFor="survey-preview-question-select"
                    >
                        <LemonSelect
                            onChange={(pageIndex) => setSelectedPageIndex(pageIndex)}
                            className="max-w-fit whitespace-nowrap"
                            value={selectedPageIndex || 0}
                            id="survey-preview-question-select"
                            options={[
                                ...survey.questions.map((question, index) => ({
                                    label: `${index + 1}. ${question.question || 'Untitled Question'}`,
                                    value: index,
                                })),
                                ...(survey.appearance?.displayThankYouMessage
                                    ? [
                                          {
                                              label: `${survey.questions.length + 1}. Confirmation`,
                                              value: survey.questions.length,
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </LemonField.Pure>
                )}
                <LemonSwitch
                    checked={surveyPreviewBackground === 'light'}
                    onChange={(checked) => setSurveyPreviewBackground(checked ? 'light' : 'dark')}
                    label={surveyPreviewBackground === 'light' ? 'Light background' : 'Dark background'}
                    className="md:self-end"
                />
            </div>
            <div
                className={clsx(
                    'border-border relative flex max-w-full items-center justify-center overflow-hidden rounded-md border shadow-lg transition-[width,height,max-height] duration-300 ease-in-out',
                    surveyPreviewBackground === 'light' ? 'bg-white' : 'bg-black'
                )}
                // easier to use inline-styles for this very specific case
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: currentDimensions.width,
                    height: currentDimensions.height,
                    maxHeight: activeScreenSize === 'desktop' ? 'calc(100% - 4rem)' : currentDimensions.height,
                }}
            >
                <SurveyAppearancePreview
                    survey={survey}
                    previewPageIndex={selectedPageIndex || 0}
                    positionStyles={{
                        position: 'absolute',
                    }}
                    onPreviewSubmit={(response) => {
                        const nextStep = getNextSurveyStep(survey, selectedPageIndex, response)
                        if (
                            nextStep === SurveyQuestionBranchingType.End &&
                            !survey.appearance?.displayThankYouMessage
                        ) {
                            return
                        }
                        setSelectedPageIndex?.(
                            nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep
                        )
                    }}
                />
            </div>
        </div>
    )
}

export function SurveyAppearanceModelTrigger(): JSX.Element {
    const { setIsAppearanceModalOpen } = useActions(surveysLogic)
    return (
        <LemonButton
            type="secondary"
            fullWidth
            icon={<IconGear />}
            onClick={() => {
                setIsAppearanceModalOpen(true)
            }}
        >
            Full-screen survey editor
        </LemonButton>
    )
}

export function SurveyAppearanceModal({
    onAppearanceChange,
    validationErrors,
    hasRatingButtons,
    hasPlaceholderText,
    survey,
    selectedPageIndex,
    setSelectedPageIndex,
}: CommonProps): JSX.Element | null {
    const { setIsAppearanceModalOpen } = useActions(surveysLogic)
    const { surveysStylingAvailable, isAppearanceModalOpen } = useValues(surveysLogic)

    if (survey.type === SurveyType.API) {
        return null
    }

    const onClose = (): void => {
        setIsAppearanceModalOpen(false)
    }

    return (
        <>
            <LemonButton
                type="secondary"
                fullWidth
                icon={<IconGear />}
                onClick={() => {
                    setIsAppearanceModalOpen(true)
                }}
            >
                Full-screen survey editor
            </LemonButton>
            <LemonModal isOpen={isAppearanceModalOpen} onClose={onClose} fullScreen simple>
                <LemonModal.Header>Customize Survey Appearance</LemonModal.Header>
                <LemonModal.Content className="flex h-full flex-1 flex-col gap-4 overflow-hidden md:flex-row">
                    <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-1">
                        {!surveysStylingAvailable && (
                            <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} className="mb-4">
                                <></>
                            </PayGateMini>
                        )}
                        <SurveyContainerAppearance
                            appearance={survey.appearance || defaultSurveyAppearance}
                            onAppearanceChange={onAppearanceChange}
                            validationErrors={validationErrors}
                            surveyType={survey.type}
                        />
                        <LemonDivider />
                        <SurveyColorsAppearance
                            appearance={survey.appearance || defaultSurveyAppearance}
                            onAppearanceChange={onAppearanceChange}
                            validationErrors={validationErrors}
                            customizeRatingButtons={hasRatingButtons}
                            customizePlaceholderText={hasPlaceholderText}
                        />
                    </div>
                    <SurveyPreview
                        survey={survey}
                        selectedPageIndex={selectedPageIndex}
                        setSelectedPageIndex={setSelectedPageIndex}
                    />
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                </LemonModal.Footer>
            </LemonModal>
        </>
    )
}
