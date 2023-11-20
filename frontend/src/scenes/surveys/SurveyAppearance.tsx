import './SurveyAppearance.scss'
import { LemonButton, LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'
import {
    SurveyAppearance as SurveyAppearanceType,
    SurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestionType,
    MultipleSurveyQuestion,
    AvailableFeature,
    BasicSurveyQuestion,
    LinkSurveyQuestion,
} from '~/types'
import { defaultSurveyAppearance } from './constants'
import {
    cancel,
    check,
    dissatisfiedEmoji,
    getTextColor,
    neutralEmoji,
    posthogLogoSVG,
    satisfiedEmoji,
    veryDissatisfiedEmoji,
    verySatisfiedEmoji,
} from './SurveyAppearanceUtils'
import { surveysLogic } from './surveysLogic'
import { useValues } from 'kea'
import React, { useEffect, useRef, useState } from 'react'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { sanitizeHTML } from './utils'

interface SurveyAppearanceProps {
    type: SurveyQuestionType
    appearance: SurveyAppearanceType
    surveyQuestionItem: SurveyQuestion
    preview?: boolean
}

interface CustomizationProps {
    appearance: SurveyAppearanceType
    surveyQuestionItem: RatingSurveyQuestion | SurveyQuestion | MultipleSurveyQuestion
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
}

interface ButtonProps {
    link?: string | null
    type?: SurveyQuestionType
    onSubmit: () => void
    appearance: SurveyAppearanceType
    children: React.ReactNode
}

const Button = ({
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
            style={{ color: textColor, backgroundColor: appearance.submitButtonColor }}
            {...other}
        >
            {children || 'Submit'}
        </button>
    )
}

export function SurveyAppearance({
    type,
    appearance,
    surveyQuestionItem,
    preview,
}: SurveyAppearanceProps): JSX.Element {
    return (
        <div data-attr="survey-preview">
            {type === SurveyQuestionType.Rating && (
                <SurveyRatingAppearance
                    preview={preview}
                    ratingSurveyQuestion={surveyQuestionItem as RatingSurveyQuestion}
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
                    disabledReason={!whitelabelAvailable ? 'Upgrade to any paid plan to hide PostHog branding' : null}
                />
            </div>
        </div>
    )
}

// This should be synced to the UI of the surveys app plugin
export function BaseAppearance({
    question,
    appearance,
    onSubmit,
    preview,
}: {
    question: BasicSurveyQuestion | LinkSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
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
            className="survey-form"
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                {!preview && (
                    <div
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
                        <Button
                            {...(preview ? { tabIndex: -1 } : null)}
                            appearance={appearance}
                            link={question.type === SurveyQuestionType.Link ? question.link : null}
                            onSubmit={onSubmit}
                            type={question.type}
                        >
                            {question.buttonText || appearance.submitButtonText}
                        </Button>
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
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
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
            className="survey-form"
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                {!preview && (
                    <div
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
                            <Button
                                {...(preview ? { tabIndex: -1 } : null)}
                                appearance={appearance}
                                onSubmit={onSubmit}
                            >
                                {ratingSurveyQuestion.buttonText || appearance.submitButtonText}
                            </Button>
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

export function SurveyMultipleChoiceAppearance({
    multipleChoiceQuestion,
    appearance,
    onSubmit,
    preview,
    initialChecked,
}: {
    multipleChoiceQuestion: MultipleSurveyQuestion
    appearance: SurveyAppearanceType
    onSubmit: () => void
    preview?: boolean
    initialChecked?: number[]
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
            className="survey-form"
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                {!preview && (
                    <div
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
                    {(multipleChoiceQuestion.choices || []).map((choice, idx) => (
                        <div className="choice-option" key={idx}>
                            <input
                                {...(initialChecked ? { checked: initialChecked.includes(idx) } : null)}
                                type={inputType}
                                name="choice"
                                value={choice}
                            />
                            <label>{choice}</label>
                            <span className="choice-check">{check}</span>
                        </div>
                    ))}
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <Button {...(preview ? { tabIndex: -1 } : null)} appearance={appearance} onSubmit={onSubmit}>
                            {multipleChoiceQuestion.buttonText || appearance.submitButtonText}
                        </Button>
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
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor || defaultSurveyAppearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="thank-you-message-container">
                <div
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
                <Button appearance={appearance} onSubmit={() => undefined}>
                    Close
                </Button>
                {!appearance.whiteLabel && (
                    <Link to="https://posthog.com" target="_blank" className="footer-branding">
                        Survey by {posthogLogoSVG}
                    </Link>
                )}
            </div>
        </div>
    )
}
