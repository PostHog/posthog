import { useId, useState } from 'react'

import {
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    Tabs,
    TabsList,
    TabsTrigger,
    cn,
} from '@posthog/quill'

import { CommonProps } from 'scenes/surveys/survey-appearance/types'

import { SurveyAppearancePreview } from '../SurveyAppearancePreview'
import { getNextPreviewPageIndex } from '../surveyPreviewNavigation'
import { clampPreviewPageIndex } from '../utils'
import { PreviewScreenSize, previewPageOptions, screenDimensions } from './SurveyAppearanceModal'

export function QuillSurveyPreview({
    selectedPageIndex,
    setSelectedPageIndex,
    survey,
}: Pick<CommonProps, 'selectedPageIndex' | 'setSelectedPageIndex' | 'survey'>): JSX.Element {
    const [activeScreenSize, setActiveScreenSize] = useState<PreviewScreenSize>('desktop')
    const [surveyPreviewBackground, setSurveyPreviewBackground] = useState<'light' | 'dark'>('light')
    const backgroundSwitchId = useId()

    const currentDimensions = screenDimensions[activeScreenSize]
    const effectivePageIndex = clampPreviewPageIndex(selectedPageIndex, survey)
    const pageOptions = previewPageOptions(survey)

    return (
        <div className="flex flex-[1.5] flex-col items-center justify-start gap-2 overflow-hidden">
            <Tabs value={activeScreenSize} onValueChange={(key) => setActiveScreenSize(key as PreviewScreenSize)}>
                <TabsList variant="line">
                    <TabsTrigger value="desktop">Desktop Web</TabsTrigger>
                    <TabsTrigger value="tablet">Tablet Web</TabsTrigger>
                    <TabsTrigger value="mobile">Mobile Web</TabsTrigger>
                </TabsList>
            </Tabs>
            <div className="flex min-w-full flex-wrap items-end justify-between gap-2">
                {setSelectedPageIndex && (
                    <Field className="max-w-sm">
                        <FieldLabel htmlFor="survey-preview-question-select">Current question</FieldLabel>
                        <Select
                            value={effectivePageIndex}
                            onValueChange={(pageIndex) => setSelectedPageIndex(pageIndex as number)}
                        >
                            <SelectTrigger id="survey-preview-question-select">
                                <SelectValue>
                                    {(value: number) => pageOptions.find((option) => option.value === value)?.label}
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {pageOptions.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                )}
                <Field orientation="horizontal" className="w-fit">
                    <Switch
                        id={backgroundSwitchId}
                        checked={surveyPreviewBackground === 'light'}
                        onCheckedChange={(checked: boolean) => setSurveyPreviewBackground(checked ? 'light' : 'dark')}
                    />
                    <FieldLabel htmlFor={backgroundSwitchId}>
                        {surveyPreviewBackground === 'light' ? 'Light background' : 'Dark background'}
                    </FieldLabel>
                </Field>
            </div>
            <div
                className={cn(
                    'relative flex max-w-full items-center justify-center overflow-hidden rounded-md border border-border shadow-lg transition-[width,height,max-height] duration-300 ease-in-out motion-reduce:transition-none',
                    // Stands in for the customer's page behind the survey, not for an app surface.
                    surveyPreviewBackground === 'light' ? 'bg-white' : 'bg-black'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: currentDimensions.width,
                    height: currentDimensions.height,
                    maxHeight: activeScreenSize === 'desktop' ? 'calc(100% - 4rem)' : currentDimensions.height,
                }}
            >
                <SurveyAppearancePreview
                    survey={survey}
                    previewPageIndex={effectivePageIndex}
                    positionStyles={{
                        position: 'absolute',
                    }}
                    onPreviewSubmit={(response) => {
                        const nextPageIndex = getNextPreviewPageIndex(survey, effectivePageIndex, response)
                        if (nextPageIndex !== null) {
                            setSelectedPageIndex?.(nextPageIndex)
                        }
                    }}
                />
            </div>
        </div>
    )
}
