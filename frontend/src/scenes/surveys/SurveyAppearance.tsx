import './SurveyAppearance.scss'

import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import React, { useEffect, useRef, useState } from 'react'

import {
    AvailableFeature,
    BasicSurveyQuestion,
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyAppearance as SurveyAppearanceType,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { defaultSurveyAppearance } from './constants'
import {
    cancel,
    check,
    dissatisfiedEmoji,
    getTextColor,
    getTextColorComponents,
    neutralEmoji,
    posthogLogoSVG,
    satisfiedEmoji,
    veryDissatisfiedEmoji,
    verySatisfiedEmoji,
} from './SurveyAppearanceUtils'
import { surveysLogic } from './surveysLogic'
import { sanitizeHTML } from './utils'

interface SurveyAppearanceProps {
    surveyType: SurveyType
    appearance: SurveyAppearanceType
    surveyQuestionItem: SurveyQuestion
    preview?: boolean
    isEditingSurvey?: boolean
}

interface CustomizationProps {
    appearance: SurveyAppearanceType
    surveyQuestionItem: RatingSurveyQuestion | SurveyQuestion | MultipleSurveyQuestion
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
}

interface WidgetCustomizationProps extends Omit<CustomizationProps, 'surveyQuestionItem'> {}

interface ButtonProps {
    link?: string | null
    type?: SurveyQuestionType
    onSubmit: () => void
    appearance: SurveyAppearanceType
    children: React.ReactNode
}

const SurveyButton = ({
    link,
    type,
    onSubmit,
    appearance,
    children,
    ...other
}: ButtonProps & React.HTMLProps<HTMLButtonElement>): JSX.Element => {
    const [textColor, setTextColor] = useState('black')
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.submitButtonColor])

    return (
        <button
            ref={ref}
            className="form-submit"
            type="button"
            onClick={() => {
                link && type === SurveyQuestionType.Link ? window.open(link) : null
                onSubmit()
            }}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ color: textColor, backgroundColor: appearance.submitButtonColor }}
            {...other}
        >
            {children || 'Submit'}
        </button>
    )
}

export function SurveyAppearance({
    surveyType,
    appearance,
    surveyQuestionItem,
    preview,
    isEditingSurvey,
}: SurveyAppearanceProps): JSX.Element {
    return (
        <div data-attr="survey-preview">
            {!preview && isEditingSurvey && surveyType === SurveyType.Widget && appearance.widgetType === 'tab' && (
                <SurveyWidgetAppearance appearance={appearance} surveyQuestionItem={surveyQuestionItem} />
            )}
            {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                <SurveyRatingAppearance
                    preview={preview}
                    ratingSurveyQuestion={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                />
            )}
            {(surveyQuestionItem.type === SurveyQuestionType.SingleChoice ||
                surveyQuestionItem.type === SurveyQuestionType.MultipleChoice) && (
                <SurveyMultipleChoiceAppearance
                    preview={preview}
                    multipleChoiceQuestion={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                />
            )}
            {(surveyQuestionItem.type === SurveyQuestionType.Open ||
                surveyQuestionItem.type === SurveyQuestionType.Link) && (
                <BaseAppearance
                    preview={preview}
                    question={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                />
            )}
        </div>
    )
}

export function Customization({ appearance, surveyQuestionItem, onAppearanceChange }: CustomizationProps): JSX.Element {
    const { whitelabelAvailable, surveysStylingAvailable } = useValues(surveysLogic)
    return (
        <>
            <div className="flex flex-col">
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}
                <div className="mt-2">Background color</div>
                <LemonInput
                    value={appearance?.backgroundColor}
                    onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    disabled={!surveysStylingAvailable}
                />
                <div className="mt-2">Border color</div>
                <LemonInput
                    value={appearance?.borderColor || defaultSurveyAppearance.borderColor}
                    onChange={(borderColor) => onAppearanceChange({ ...appearance, borderColor })}
                    disabled={!surveysStylingAvailable}
                />
                <>
                    <div className="mt-2">Position</div>
                    <div className="flex gap-1">
                        {['left', 'center', 'right'].map((position) => {
                            return (
                                <LemonButton
                                    key={position}
                                    type="tertiary"
                                    onClick={() => onAppearanceChange({ ...appearance, position })}
                                    active={appearance.position === position}
                                    disabledReason={
                                        surveysStylingAvailable
                                            ? null
                                            : 'Subscribe to surveys to customize survey position.'
                                    }
                                >
                                    {position}
                                </LemonButton>
                            )
                        })}
                    </div>
                </>
                {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                    <>
                        <div className="mt-2">Rating button color</div>
                        <LemonInput
                            value={appearance?.ratingButtonColor}
                            onChange={(ratingButtonColor) => onAppearanceChange({ ...appearance, ratingButtonColor })}
                            disabled={!surveysStylingAvailable}
                        />
                        <div className="mt-2">Rating button active color</div>
                        <LemonInput
                            value={appearance?.ratingButtonActiveColor}
                            onChange={(ratingButtonActiveColor) =>
                                onAppearanceChange({ ...appearance, ratingButtonActiveColor })
                            }
                            disabled={!surveysStylingAvailable}
                        />
                    </>
                )}
                <div className="mt-2">Button color</div>
                <LemonInput
                    value={appearance?.submitButtonColor}
                    onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                    disabled={!surveysStylingAvailable}
                />
                {surveyQuestionItem.type === SurveyQuestionType.Open && (
                    <>
                        <div className="mt-2">Placeholder</div>
                        <LemonInput
                            value={appearance?.placeholder || defaultSurveyAppearance.placeholder}
                            onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
                            disabled={!surveysStylingAvailable}
                        />
                    </>
                )}
                <div className="mt-2">
                    <LemonCheckbox
                        label={
                            <div className="flex items-center">
                                <span>Hide PostHog branding</span>
                            </div>
                        }
                        onChange={(checked) => onAppearanceChange({ ...appearance, whiteLabel: checked })}
                        checked={appearance?.whiteLabel}
                        disabledReason={
                            !whitelabelAvailable ? 'Upgrade to any paid plan to hide PostHog branding' : null
                        }
                    />
                </div>
            </div>
        </>
    )
}

export function WidgetCustomization({ appearance, onAppearanceChange }: WidgetCustomizationProps): JSX.Element {
    return (
        <>
            <div className="mt-2">Feedback button type</div>
            <LemonSelect
                value={appearance.widgetType}
                onChange={(widgetType) => onAppearanceChange({ ...appearance, widgetType })}
                options={[
                    { label: 'Embedded tab', value: 'tab' },
                    { label: 'Custom', value: 'selector' },
                ]}
            />
            {appearance.widgetType === 'selector' ? (
                <>
                    <div className="mt-2">Class or ID selector</div>
                    <LemonInput
                        value={appearance.widgetSelector}
                        onChange={(widgetSelector) => onAppearanceChange({ ...appearance, widgetSelector })}
                        placeholder="ex: .feedback-button, #feedback-button"
                    />
                </>
            ) : (
                <>
                    <div className="mt-2">Label</div>
                    <LemonInput
                        value={appearance.widgetLabel}
                        onChange={(widgetLabel) => onAppearanceChange({ ...appearance, widgetLabel })}
                    />
                    <div className="mt-2">Background color</div>
                    <LemonInput
                        value={appearance.widgetColor}
                        onChange={(widgetColor) => onAppearanceChange({ ...appearance, widgetColor })}
                        placeholder="#e0a045"
                    />
                </>
            )}
        </>
    )
}

// This should be synced to the UI of the surveys app plugin
export function BaseAppearance({
    question,
    appearance,
    onSubmit,
    preview,
    isWidgetSurvey,
}: {
    question: BasicSurveyQuestion | LinkSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
    isWidgetSurvey?: boolean
}): JSX.Element {
    const [textColor, setTextColor] = useState<'white' | 'black'>('black')
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.backgroundColor])

    return (
        <form
            ref={ref}
            className={`survey-form ${isWidgetSurvey ? 'widget-survey' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    backgroundColor: appearance.backgroundColor,
                    border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                    color: textColor,
                    '--survey-text-color': getTextColorComponents(textColor),
                } as React.CSSProperties
            }
        >
            <div className="survey-box">
                {!preview && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                        }}
                        className="cancel-btn-wrapper"
                    >
                        <button className="form-cancel" type="button">
                            {cancel}
                        </button>
                    </div>
                )}
                <div className="question-textarea-wrapper">
                    <div
                        className="survey-question"
                        dangerouslySetInnerHTML={{ __html: sanitizeHTML(question.question) }}
                    />
                    {/* Using dangerouslySetInnerHTML is safe here, because it's taking the user's input and showing it to the same user.
                    They can try passing in arbitrary scripts, but it would show up only for them, so it's like trying to XSS yourself, where
                    you already have all the data. Furthermore, sanitization should catch all obvious attempts */}
                    {question.description && (
                        <div
                            className="description"
                            dangerouslySetInnerHTML={{ __html: sanitizeHTML(question.description) }}
                        />
                    )}
                    {question.type === SurveyQuestionType.Open && (
                        <textarea
                            {...(preview ? { tabIndex: -1 } : null)}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                border: `1px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                            }}
                            className="survey-textarea"
                            name="survey"
                            rows={4}
                            placeholder={appearance.placeholder}
                        />
                    )}
                </div>

                <div className="bottom-section">
                    <div className="buttons">
                        <SurveyButton
                            {...(preview ? { tabIndex: -1 } : null)}
                            appearance={appearance}
                            link={question.type === SurveyQuestionType.Link ? question.link : null}
                            onSubmit={onSubmit}
                            type={question.type}
                        >
                            {question.buttonText || appearance.submitButtonText}
                        </SurveyButton>
                    </div>

                    {!preview && !appearance.whiteLabel && (
                        <Link to="https://posthog.com" target="_blank" className="footer-branding">
                            Survey by {posthogLogoSVG}
                        </Link>
                    )}
                </div>
            </div>
        </form>
    )
}

const RatingButton = ({
    num,
    active,
    appearance,
    setActiveNumber,
    preview,
}: {
    num: number
    active: boolean
    appearance: SurveyAppearanceType
    setActiveNumber: (num: number) => void
    preview?: boolean
}): JSX.Element => {
    const [textColor, setTextColor] = useState('black')
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.ratingButtonActiveColor, appearance.ratingButtonColor, active])

    return (
        <button
            {...(preview ? { tabIndex: -1 } : null)}
            ref={ref}
            className="ratings-number"
            type="button"
            onClick={() => setActiveNumber(num)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color: textColor,
                backgroundColor: active ? appearance.ratingButtonActiveColor : appearance.ratingButtonColor,
                borderColor: appearance.borderColor || defaultSurveyAppearance.borderColor,
            }}
        >
            {num}
        </button>
    )
}

const NumberRating = ({
    appearance,
    ratingSurveyQuestion,
    preview,
}: {
    appearance: SurveyAppearanceType
    ratingSurveyQuestion: RatingSurveyQuestion
    preview?: boolean
}): JSX.Element => {
    const [activeNumber, setActiveNumber] = useState<number | undefined>()

    const totalNumbers = ratingSurveyQuestion.scale === 10 ? 11 : ratingSurveyQuestion.scale
    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                gridTemplateColumns: `repeat(${totalNumbers}, minmax(0, 1fr))`,
            }}
            className={`rating-options-buttons ${ratingSurveyQuestion.scale === 5 ? '' : 'max-numbers'}`}
        >
            {(ratingSurveyQuestion.scale === 10 ? [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] : [1, 2, 3, 4, 5]).map(
                (num, idx) => {
                    const active = activeNumber === num
                    return (
                        <RatingButton
                            preview={preview}
                            key={idx}
                            active={active}
                            appearance={appearance}
                            num={num}
                            setActiveNumber={setActiveNumber}
                        />
                    )
                }
            )}
        </div>
    )
}

const EmojiRating = ({
    ratingSurveyQuestion,
    appearance,
    preview,
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
    preview?: boolean
}): JSX.Element => {
    const [activeIndex, setActiveIndex] = useState<number | undefined>()
    const threeEmojis = [dissatisfiedEmoji, neutralEmoji, satisfiedEmoji]
    const fiveEmojis = [veryDissatisfiedEmoji, dissatisfiedEmoji, neutralEmoji, satisfiedEmoji, verySatisfiedEmoji]

    return (
        <div className="rating-options-emoji">
            {(ratingSurveyQuestion.scale === 3 ? threeEmojis : fiveEmojis).map((emoji, idx) => {
                const active = idx === activeIndex
                return (
                    <button
                        {...(preview ? { tabIndex: -1 } : null)}
                        className="ratings-emoji"
                        type="button"
                        key={idx}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ fill: active ? appearance.ratingButtonActiveColor : appearance.ratingButtonColor }}
                        onClick={() => setActiveIndex(idx)}
                    >
                        {emoji}
                    </button>
                )
            })}
        </div>
    )
}

export function SurveyRatingAppearance({
    ratingSurveyQuestion,
    appearance,
    onSubmit,
    preview,
    isWidgetSurvey,
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
    isWidgetSurvey?: boolean
}): JSX.Element {
    const [textColor, setTextColor] = useState('black')
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.backgroundColor])

    return (
        <form
            ref={ref}
            className={`survey-form ${isWidgetSurvey ? 'widget-survey' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                {!preview && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                        }}
                        className="cancel-btn-wrapper"
                    >
                        <button className="form-cancel" type="button">
                            {cancel}
                        </button>
                    </div>
                )}
                <div
                    className="survey-question"
                    dangerouslySetInnerHTML={{ __html: sanitizeHTML(ratingSurveyQuestion.question) }}
                />
                {ratingSurveyQuestion.description && (
                    <div
                        className="description"
                        dangerouslySetInnerHTML={{ __html: sanitizeHTML(ratingSurveyQuestion.description) }}
                    />
                )}
                <div className="rating-section">
                    <div className="rating-options">
                        {ratingSurveyQuestion.display === 'emoji' && (
                            <EmojiRating
                                preview={preview}
                                appearance={appearance}
                                ratingSurveyQuestion={ratingSurveyQuestion}
                            />
                        )}
                        {ratingSurveyQuestion.display === 'number' && (
                            <NumberRating
                                preview={preview}
                                appearance={appearance}
                                ratingSurveyQuestion={ratingSurveyQuestion}
                            />
                        )}
                    </div>
                    <div className="rating-text">
                        <div>{ratingSurveyQuestion.lowerBoundLabel}</div>
                        <div>{ratingSurveyQuestion.upperBoundLabel}</div>
                    </div>

                    <div className="bottom-section">
                        <div className="buttons">
                            <SurveyButton
                                {...(preview ? { tabIndex: -1 } : null)}
                                appearance={appearance}
                                onSubmit={onSubmit}
                            >
                                {ratingSurveyQuestion.buttonText || appearance.submitButtonText}
                            </SurveyButton>
                        </div>

                        {!preview && !appearance.whiteLabel && (
                            <Link to="https://posthog.com" target="_blank" className="footer-branding">
                                Survey by {posthogLogoSVG}
                            </Link>
                        )}
                    </div>
                </div>
            </div>
        </form>
    )
}

const OpenEndedChoice = ({
    label,
    initialChecked,
    inputType,
    index,
}: {
    label: string
    initialChecked: boolean
    inputType: string
    textColor: string
    index: number
}): JSX.Element => {
    const textRef = useRef<HTMLInputElement | null>(null)
    const checkRef = useRef<HTMLInputElement | null>(null)

    return (
        <div
            className="choice-option choice-option-open"
            onClick={() => {
                if (checkRef.current?.checked || checkRef.current?.disabled) {
                    textRef.current?.focus()
                }
            }}
        >
            <input
                id={`${label}-${index}`}
                ref={checkRef}
                type={inputType}
                disabled={!initialChecked || !checkRef.current?.value}
                defaultChecked={initialChecked}
                name="choice"
            />
            <label htmlFor={`${label}-${index}`}>
                <span>{label}:</span>
                <input
                    ref={textRef}
                    type="text"
                    maxLength={100}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                        if (checkRef.current) {
                            checkRef.current.value = e.target.value
                            if (e.target.value) {
                                checkRef.current.disabled = false
                                checkRef.current.checked = true
                            } else {
                                checkRef.current.disabled = true
                                checkRef.current.checked = false
                            }
                        }
                    }}
                />
            </label>
            <span className="choice-check">{check}</span>
        </div>
    )
}

export function SurveyMultipleChoiceAppearance({
    multipleChoiceQuestion,
    appearance,
    onSubmit,
    preview,
    initialChecked,
    isWidgetSurvey,
}: {
    multipleChoiceQuestion: MultipleSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
    initialChecked?: number[]
    isWidgetSurvey?: boolean
}): JSX.Element {
    const [textColor, setTextColor] = useState('black')
    const ref = useRef(null)
    const inputType = multipleChoiceQuestion.type === SurveyQuestionType.SingleChoice ? 'radio' : 'checkbox'

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.backgroundColor])

    return (
        <form
            ref={ref}
            className={`survey-form ${isWidgetSurvey ? 'widget-survey' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                {!preview && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                        }}
                        className="cancel-btn-wrapper"
                    >
                        <button className="form-cancel" type="button">
                            {cancel}
                        </button>
                    </div>
                )}
                <div
                    className="survey-question"
                    dangerouslySetInnerHTML={{ __html: sanitizeHTML(multipleChoiceQuestion.question) }}
                />
                {multipleChoiceQuestion.description && (
                    <div
                        className="description"
                        dangerouslySetInnerHTML={{ __html: sanitizeHTML(multipleChoiceQuestion.description) }}
                    />
                )}
                <div className="multiple-choice-options">
                    {(multipleChoiceQuestion.choices || []).map((choice, idx) =>
                        multipleChoiceQuestion?.hasOpenChoice && idx === multipleChoiceQuestion.choices?.length - 1 ? (
                            <OpenEndedChoice
                                key={idx}
                                index={idx}
                                initialChecked={!!initialChecked?.includes(idx)}
                                inputType={inputType}
                                label={choice}
                                textColor={textColor}
                            />
                        ) : (
                            <div className="choice-option" key={idx}>
                                <input
                                    {...(initialChecked ? { defaultChecked: initialChecked.includes(idx) } : null)}
                                    type={inputType}
                                    name="choice"
                                    value={choice}
                                />
                                <label>{choice}</label>
                                <span className="choice-check">{check}</span>
                            </div>
                        )
                    )}
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <SurveyButton
                            {...(preview ? { tabIndex: -1 } : null)}
                            appearance={appearance}
                            onSubmit={onSubmit}
                        >
                            {multipleChoiceQuestion.buttonText || appearance.submitButtonText}
                        </SurveyButton>
                    </div>

                    {!preview && !appearance.whiteLabel && (
                        <Link to="https://posthog.com" target="_blank" className="footer-branding">
                            Survey by {posthogLogoSVG}
                        </Link>
                    )}
                </div>
            </div>
        </form>
    )
}

export function SurveyThankYou({ appearance }: { appearance: SurveyAppearanceType }): JSX.Element {
    const [textColor, setTextColor] = useState('black')
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.backgroundColor])

    return (
        <div
            ref={ref}
            className="thank-you-message"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="thank-you-message-container">
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}` }}
                    className="cancel-btn-wrapper"
                >
                    <button className="form-cancel" type="button" onClick={() => undefined}>
                        {cancel}
                    </button>
                </div>
                <h3
                    className="thank-you-message-header"
                    dangerouslySetInnerHTML={{
                        __html: sanitizeHTML(appearance?.thankYouMessageHeader || 'Thank you!'),
                    }}
                />
                <div
                    className="thank-you-message-body"
                    dangerouslySetInnerHTML={{ __html: sanitizeHTML(appearance?.thankYouMessageDescription || '') }}
                />
                <SurveyButton appearance={appearance} onSubmit={() => undefined}>
                    Close
                </SurveyButton>
                {!appearance.whiteLabel && (
                    <Link to="https://posthog.com" target="_blank" className="footer-branding">
                        Survey by {posthogLogoSVG}
                    </Link>
                )}
            </div>
        </div>
    )
}

export function SurveyWidgetAppearance({
    appearance,
    surveyQuestionItem,
}: {
    appearance: SurveyAppearanceType
    surveyQuestionItem: SurveyQuestion
}): JSX.Element {
    const [textColor, setTextColor] = useState('black')
    const [displaySurveyBox, setDisplaySurveyBox] = useState(false)
    const ref = useRef(null)

    useEffect(() => {
        if (ref.current) {
            const textColor = getTextColor(ref.current)
            setTextColor(textColor)
        }
    }, [appearance.widgetColor])

    useEffect(() => {
        const widgetSurvey = document.getElementsByClassName('widget-survey')[0] as HTMLFormElement
        widgetSurvey.style.display = displaySurveyBox ? 'block' : 'none'
        if (displaySurveyBox) {
            const widget = document.getElementsByClassName('ph-survey-widget-tab')[0]
            const widgetPos = widget.getBoundingClientRect()
            widgetSurvey.style.position = 'fixed'
            widgetSurvey.style.zIndex = '9999999'
            widgetSurvey.style.top = '50%'
            widgetSurvey.style.left = `${widgetPos.right - 360}px`
        }
    }, [displaySurveyBox, surveyQuestionItem])

    return (
        <>
            <div
                className="ph-survey-widget-tab auto-text-color"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: appearance.widgetColor || '#e0a045',
                    color: textColor,
                }}
                onClick={() => setDisplaySurveyBox(!displaySurveyBox)}
            >
                <div className="ph-survey-widget-tab-icon" />
                {appearance?.widgetLabel || ''}
            </div>
            {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                <SurveyRatingAppearance
                    preview={false}
                    ratingSurveyQuestion={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                    isWidgetSurvey={true}
                />
            )}
            {(surveyQuestionItem.type === SurveyQuestionType.SingleChoice ||
                surveyQuestionItem.type === SurveyQuestionType.MultipleChoice) && (
                <SurveyMultipleChoiceAppearance
                    preview={false}
                    multipleChoiceQuestion={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                    isWidgetSurvey={true}
                />
            )}
            {(surveyQuestionItem.type === SurveyQuestionType.Open ||
                surveyQuestionItem.type === SurveyQuestionType.Link) && (
                <BaseAppearance
                    preview={false}
                    question={surveyQuestionItem}
                    appearance={appearance}
                    onSubmit={() => undefined}
                    isWidgetSurvey={true}
                />
            )}
        </>
    )
}
