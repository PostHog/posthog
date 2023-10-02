import './SurveyAppearance.scss'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'
import {
    SurveyAppearance as SurveyAppearanceType,
    SurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestionType,
    MultipleSurveyQuestion,
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
import { useEffect, useRef, useState } from 'react'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

interface SurveyAppearanceProps {
    type: SurveyQuestionType
    question: string
    appearance: SurveyAppearanceType
    surveyQuestionItem: RatingSurveyQuestion | SurveyQuestion | MultipleSurveyQuestion
    description?: string | null
    link?: string | null
    readOnly?: boolean
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
}

const Button = ({
    link,
    type,
    onSubmit,
    appearance,
    children,
}: {
    link?: string | null
    type?: SurveyQuestionType
    onSubmit: () => void
    appearance: SurveyAppearanceType
    children: React.ReactNode
}): JSX.Element => {
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
        >
            {children || 'Submit'}
        </button>
    )
}

export function SurveyAppearance({
    type,
    question,
    appearance,
    surveyQuestionItem,
    description,
    link,
    readOnly,
    onAppearanceChange,
}: SurveyAppearanceProps): JSX.Element {
    const { whitelabelAvailable } = useValues(surveysLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [showThankYou, setShowThankYou] = useState(false)
    const [hideSubmittedSurvey, setHideSubmittedSurvey] = useState(false)

    useEffect(() => {
        if (appearance.displayThankYouMessage && showThankYou) {
            setHideSubmittedSurvey(true)
        } else {
            setHideSubmittedSurvey(false)
        }
    }, [showThankYou])

    return (
        <>
            <h3 className="mb-4 text-center">Preview</h3>
            {!hideSubmittedSurvey && (
                <>
                    {type === SurveyQuestionType.Rating && (
                        <SurveyRatingAppearance
                            ratingSurveyQuestion={surveyQuestionItem as RatingSurveyQuestion}
                            appearance={appearance}
                            question={question}
                            description={description}
                            onSubmit={() => appearance.displayThankYouMessage && setShowThankYou(true)}
                        />
                    )}
                    {(surveyQuestionItem.type === SurveyQuestionType.SingleChoice ||
                        surveyQuestionItem.type === SurveyQuestionType.MultipleChoice) && (
                        <SurveyMultipleChoiceAppearance
                            multipleChoiceQuestion={surveyQuestionItem as MultipleSurveyQuestion}
                            appearance={appearance}
                            question={question}
                            description={description}
                            onSubmit={() => appearance.displayThankYouMessage && setShowThankYou(true)}
                        />
                    )}
                    {(surveyQuestionItem.type === SurveyQuestionType.Open ||
                        surveyQuestionItem.type === SurveyQuestionType.Link) && (
                        <BaseAppearance
                            type={type}
                            question={question}
                            description={description}
                            appearance={appearance}
                            link={link}
                            onSubmit={() => appearance.displayThankYouMessage && setShowThankYou(true)}
                        />
                    )}
                </>
            )}
            {showThankYou && <SurveyThankYou appearance={appearance} setShowThankYou={setShowThankYou} />}
            {!readOnly && (
                <div className="flex flex-col">
                    <div className="mt-2">Background color</div>
                    <LemonInput
                        value={appearance?.backgroundColor}
                        onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    />
                    <div className="mt-2">Border color</div>
                    <LemonInput
                        value={appearance?.borderColor}
                        onChange={(borderColor) => onAppearanceChange({ ...appearance, borderColor })}
                    />
                    {featureFlags[FEATURE_FLAGS.SURVEYS_POSITIONS] && (
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
                                        >
                                            {position}
                                        </LemonButton>
                                    )
                                })}
                            </div>
                        </>
                    )}
                    {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                        <>
                            <div className="mt-2">Rating button color</div>
                            <LemonInput
                                value={appearance?.ratingButtonColor}
                                onChange={(ratingButtonColor) =>
                                    onAppearanceChange({ ...appearance, ratingButtonColor })
                                }
                            />
                            <div className="mt-2">Rating button active color</div>
                            <LemonInput
                                value={appearance?.ratingButtonActiveColor}
                                onChange={(ratingButtonActiveColor) =>
                                    onAppearanceChange({ ...appearance, ratingButtonActiveColor })
                                }
                            />
                        </>
                    )}
                    <div className="mt-2">Button color</div>
                    <LemonInput
                        value={appearance?.submitButtonColor}
                        onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                    />
                    <div className="mt-2">Button text</div>
                    <LemonInput
                        value={appearance?.submitButtonText || defaultSurveyAppearance.submitButtonText}
                        onChange={(submitButtonText) => onAppearanceChange({ ...appearance, submitButtonText })}
                    />
                    {surveyQuestionItem.type === SurveyQuestionType.Open && (
                        <>
                            <div className="mt-2">Placeholder</div>
                            <LemonInput
                                value={appearance?.placeholder || defaultSurveyAppearance.placeholder}
                                onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
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
                            disabledReason={
                                !whitelabelAvailable ? 'Upgrade to any paid plan to hide PostHog branding' : null
                            }
                        />
                    </div>
                </div>
            )}
        </>
    )
}

// This should be synced to the UI of the surveys app plugin
function BaseAppearance({
    type,
    question,
    appearance,
    onSubmit,
    description,
    link,
}: {
    type: SurveyQuestionType
    question: string
    appearance: SurveyAppearanceType
    onSubmit: () => void
    description?: string | null
    link?: string | null
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
                border: `1.5px solid ${appearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                <div style={{ border: `1.5px solid ${appearance.borderColor}` }} className="cancel-btn-wrapper">
                    <button className="form-cancel" type="button">
                        {cancel}
                    </button>
                </div>
                <div className="question-textarea-wrapper">
                    <div className="survey-question">{question}</div>
                    {description && <div className="description">{description}</div>}
                    {type === SurveyQuestionType.Open && (
                        <textarea
                            style={{ border: `1px solid ${appearance.borderColor}` }}
                            className="survey-textarea"
                            name="survey"
                            rows={4}
                            placeholder={appearance.placeholder}
                        />
                    )}
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <Button appearance={appearance} link={link} onSubmit={onSubmit} type={type}>
                            {appearance.submitButtonText}
                        </Button>
                    </div>
                    {!appearance.whiteLabel && (
                        <a href="https://posthog.com" target="_blank" rel="noopener" className="footer-branding">
                            Survey by {posthogLogoSVG}
                        </a>
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
}: {
    num: number
    active: boolean
    appearance: SurveyAppearanceType
    setActiveNumber: (num: number) => void
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
            ref={ref}
            className="ratings-number"
            type="button"
            onClick={() => setActiveNumber(num)}
            style={{
                color: textColor,
                backgroundColor: active ? appearance.ratingButtonActiveColor : appearance.ratingButtonColor,
                borderColor: appearance.borderColor,
            }}
        >
            {num}
        </button>
    )
}

const NumberRating = ({
    appearance,
    ratingSurveyQuestion,
}: {
    appearance: SurveyAppearanceType
    ratingSurveyQuestion: RatingSurveyQuestion
}): JSX.Element => {
    const [activeNumber, setActiveNumber] = useState<number | undefined>()
    return (
        <div
            style={{
                border: `1.5px solid ${appearance.borderColor}`,
                gridTemplateColumns: `repeat(${ratingSurveyQuestion.scale}, minmax(0, 1fr))`,
            }}
            className={`rating-options-buttons ${ratingSurveyQuestion.scale === 5 ? '' : 'max-numbers'}`}
        >
            {(ratingSurveyQuestion.scale === 5 ? [1, 2, 3, 4, 5] : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]).map((num, idx) => {
                const active = activeNumber === num
                return (
                    <RatingButton
                        key={idx}
                        active={active}
                        appearance={appearance}
                        num={num}
                        setActiveNumber={setActiveNumber}
                    />
                )
            })}
        </div>
    )
}

const EmojiRating = ({
    ratingSurveyQuestion,
    appearance,
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
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

function SurveyRatingAppearance({
    ratingSurveyQuestion,
    appearance,
    question,
    onSubmit,
    description,
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
    question: string
    onSubmit: () => void
    description?: string | null
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
                border: `1.5px solid ${appearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                <div style={{ border: `1.5px solid ${appearance.borderColor}` }} className="cancel-btn-wrapper">
                    <button className="form-cancel" type="button">
                        {cancel}
                    </button>
                </div>
                <div className="survey-question">{question}</div>
                {description && <div className="description">{description}</div>}
                <div className="rating-section">
                    <div className="rating-options">
                        {ratingSurveyQuestion.display === 'emoji' && (
                            <EmojiRating appearance={appearance} ratingSurveyQuestion={ratingSurveyQuestion} />
                        )}
                        {ratingSurveyQuestion.display === 'number' && (
                            <NumberRating appearance={appearance} ratingSurveyQuestion={ratingSurveyQuestion} />
                        )}
                    </div>
                    <div className="rating-text">
                        <div>{ratingSurveyQuestion.lowerBoundLabel}</div>
                        <div>{ratingSurveyQuestion.upperBoundLabel}</div>
                    </div>
                    <div className="bottom-section">
                        <div className="buttons">
                            <Button appearance={appearance} onSubmit={onSubmit}>
                                {appearance.submitButtonText}
                            </Button>
                        </div>
                        {!appearance.whiteLabel && (
                            <a href="https://posthog.com" target="_blank" rel="noopener" className="footer-branding">
                                Survey by {posthogLogoSVG}
                            </a>
                        )}
                    </div>
                </div>
            </div>
        </form>
    )
}

function SurveyMultipleChoiceAppearance({
    multipleChoiceQuestion,
    appearance,
    question,
    onSubmit,
    description,
}: {
    multipleChoiceQuestion: MultipleSurveyQuestion
    appearance: SurveyAppearanceType
    question: string
    onSubmit: () => void
    description?: string | null
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
                border: `1.5px solid ${appearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="survey-box">
                <div style={{ border: `1.5px solid ${appearance.borderColor}` }} className="cancel-btn-wrapper">
                    <button className="form-cancel" type="button">
                        {cancel}
                    </button>
                </div>
                <div className="survey-question">{question}</div>
                {description && <div className="description">{description}</div>}
                <div className="multiple-choice-options">
                    {(multipleChoiceQuestion.choices || []).map((choice, idx) => (
                        <div className="choice-option" key={idx}>
                            <input type={inputType} name="choice" value={choice} />
                            <label>{choice}</label>
                            <span className="choice-check">{check}</span>
                        </div>
                    ))}
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <Button appearance={appearance} onSubmit={onSubmit}>
                            {appearance.submitButtonText}
                        </Button>
                    </div>
                    {!appearance.whiteLabel && (
                        <a href="https://posthog.com" target="_blank" rel="noopener" className="footer-branding">
                            Survey by {posthogLogoSVG}
                        </a>
                    )}
                </div>
            </div>
        </form>
    )
}

function SurveyThankYou({
    appearance,
    setShowThankYou,
}: {
    appearance: SurveyAppearanceType
    setShowThankYou: (show: boolean) => void
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
        <div
            ref={ref}
            className="thank-you-message"
            style={{
                backgroundColor: appearance.backgroundColor,
                border: `1.5px solid ${appearance.borderColor}`,
                color: textColor,
            }}
        >
            <div className="thank-you-message-container">
                <div style={{ border: `1.5px solid ${appearance.borderColor}` }} className="cancel-btn-wrapper">
                    <button className="form-cancel" type="button" onClick={() => setShowThankYou(false)}>
                        {cancel}
                    </button>
                </div>
                <h3 className="thank-you-message-header">{appearance?.thankYouMessageHeader || 'Thank you!'}</h3>
                <div className="thank-you-message-body">{appearance?.thankYouMessageDescription || ''}</div>
                <Button appearance={appearance} onSubmit={() => setShowThankYou(false)}>
                    Close
                </Button>
                {!appearance.whiteLabel && (
                    <a href="https://posthog.com" target="_blank" rel="noopener" className="footer-branding">
                        Survey by {posthogLogoSVG}
                    </a>
                )}
            </div>
        </div>
    )
}
