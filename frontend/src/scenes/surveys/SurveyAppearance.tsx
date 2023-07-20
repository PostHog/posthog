import './SurveyAppearance.scss'
import { LemonInput } from '@posthog/lemon-ui'
import {
    SurveyAppearance as SurveyAppearanceType,
    SurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestionType,
} from '~/types'
import { defaultSurveyAppearance } from './surveyLogic'
import {
    dissatisfiedEmoji,
    neutralEmoji,
    posthogLogoSVG,
    satisfiedEmoji,
    veryDissatisfiedEmoji,
    verySatisfiedEmoji,
} from './SurveyAppearanceUtils'

interface SurveyAppearanceProps {
    type: SurveyQuestionType
    question: string
    appearance: SurveyAppearanceType
    surveyQuestionItem: RatingSurveyQuestion | SurveyQuestion
    description?: string | null
    link?: string | null
    readOnly?: boolean
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
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
    return (
        <>
            <h3 className="mb-4 text-center">Preview</h3>
            {type === SurveyQuestionType.Rating ? (
                <SurveyRatingAppearance
                    ratingSurveyQuestion={surveyQuestionItem as RatingSurveyQuestion}
                    appearance={appearance}
                    question={question}
                    description={description}
                />
            ) : (
                <BaseAppearance
                    type={type}
                    question={question}
                    description={description}
                    appearance={appearance}
                    link={link}
                />
            )}
            {!readOnly && (
                <div className="flex flex-col">
                    <div className="mt-2">Background color</div>
                    <LemonInput
                        value={appearance?.backgroundColor}
                        onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    />
                    <div className="mt-2">Question text color</div>
                    <LemonInput
                        value={appearance?.textColor}
                        onChange={(textColor) => onAppearanceChange({ ...appearance, textColor })}
                    />
                    <div className="mt-2">Description text color</div>
                    <LemonInput
                        value={appearance?.descriptionTextColor || defaultSurveyAppearance.descriptionTextColor}
                        onChange={(descriptionTextColor) => onAppearanceChange({ ...appearance, descriptionTextColor })}
                    />
                    {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                        <>
                            <div className="mt-2">Rating button color</div>
                            <LemonInput
                                value={appearance?.ratingButtonColor}
                                onChange={(ratingButtonColor) =>
                                    onAppearanceChange({ ...appearance, ratingButtonColor })
                                }
                            />
                            {surveyQuestionItem.display === 'emoji' && (
                                <>
                                    <div className="mt-2">Rating button hover color</div>
                                    <LemonInput
                                        value={appearance?.ratingButtonHoverColor}
                                        onChange={(ratingButtonHoverColor) =>
                                            onAppearanceChange({ ...appearance, ratingButtonHoverColor })
                                        }
                                    />
                                </>
                            )}
                        </>
                    )}
                    {(type === SurveyQuestionType.Open || type === SurveyQuestionType.Link) && (
                        <>
                            <div className="mt-2">Submit button color</div>
                            <LemonInput
                                value={appearance?.submitButtonColor}
                                onChange={(submitButtonColor) =>
                                    onAppearanceChange({ ...appearance, submitButtonColor })
                                }
                            />
                            <div className="mt-2">Submit button text</div>
                            <LemonInput
                                value={appearance?.submitButtonText || defaultSurveyAppearance.submitButtonText}
                                onChange={(submitButtonText) => onAppearanceChange({ ...appearance, submitButtonText })}
                            />
                        </>
                    )}
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
    description,
    link,
}: {
    type: SurveyQuestionType
    question: string
    appearance: SurveyAppearanceType
    description?: string | null
    link?: string | null
}): JSX.Element {
    return (
        <form className="survey-form" style={{ backgroundColor: appearance.backgroundColor }}>
            <div className="survey-box">
                <div className="cancel-btn-wrapper">
                    <button
                        className="form-cancel"
                        type="button"
                        style={{ backgroundColor: appearance.backgroundColor }}
                    >
                        X
                    </button>
                </div>
                <div className="question-textarea-wrapper">
                    <div className="survey-question" style={{ color: appearance.textColor }}>
                        {question}
                    </div>
                    {description && (
                        <div className="description" style={{ color: appearance.descriptionTextColor }}>
                            {description}
                        </div>
                    )}
                    {type === SurveyQuestionType.Open && (
                        <textarea className="survey-textarea" name="survey" rows={4} />
                    )}
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <button
                            className="form-submit"
                            type="button"
                            onClick={() => {
                                link && type === SurveyQuestionType.Link ? window.open(link) : null
                            }}
                            style={{ backgroundColor: appearance.submitButtonColor }}
                        >
                            {appearance.submitButtonText || 'Submit'}
                        </button>
                    </div>
                    <div className="footer-branding">powered by {posthogLogoSVG} PostHog</div>
                </div>
            </div>
        </form>
    )
}

function SurveyRatingAppearance({
    ratingSurveyQuestion,
    appearance,
    question,
    description,
}: {
    ratingSurveyQuestion: RatingSurveyQuestion
    appearance: SurveyAppearanceType
    question: string
    description?: string | null
}): JSX.Element {
    const threeEmojis = [dissatisfiedEmoji, neutralEmoji, satisfiedEmoji]
    const fiveEmojis = [veryDissatisfiedEmoji, dissatisfiedEmoji, neutralEmoji, satisfiedEmoji, verySatisfiedEmoji]

    return (
        <form className="survey-form" style={{ backgroundColor: appearance.backgroundColor }}>
            <div className="survey-box">
                <div className="cancel-btn-wrapper">
                    <button
                        className="form-cancel"
                        type="button"
                        style={{ backgroundColor: appearance.backgroundColor }}
                    >
                        X
                    </button>
                </div>
                <div className="survey-question" style={{ color: appearance.textColor }}>
                    {question}
                </div>
                {description && (
                    <div className="description" style={{ color: appearance.descriptionTextColor }}>
                        {description}
                    </div>
                )}
                <div className="rating-section">
                    <div className="rating-options">
                        {ratingSurveyQuestion.display === 'emoji' && (
                            <div className="rating-options-emoji">
                                {(ratingSurveyQuestion.scale === 3 ? threeEmojis : fiveEmojis).map((emoji, idx) => (
                                    <button
                                        className="ratings-emoji"
                                        type="button"
                                        key={idx}
                                        style={{ fill: appearance.ratingButtonColor }}
                                        onMouseEnter={(val) => {
                                            val.currentTarget.style.fill = appearance.ratingButtonHoverColor || 'coral'
                                        }}
                                        onMouseLeave={(val) => {
                                            val.currentTarget.style.fill = appearance.ratingButtonColor || 'black'
                                        }}
                                    >
                                        {emoji}
                                    </button>
                                ))}
                            </div>
                        )}{' '}
                        {ratingSurveyQuestion.display === 'number' && (
                            <div>
                                {
                                    <div
                                        className={`rating-options-buttons ${
                                            ratingSurveyQuestion.scale === 5 ? '' : 'max-numbers'
                                        }`}
                                    >
                                        {(ratingSurveyQuestion.scale === 5
                                            ? [1, 2, 3, 4, 5]
                                            : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                                        ).map((num, idx) => {
                                            return (
                                                <button
                                                    className="ratings-number"
                                                    type="button"
                                                    key={idx}
                                                    style={{ backgroundColor: appearance.ratingButtonColor }}
                                                >
                                                    {num}
                                                </button>
                                            )
                                        })}
                                    </div>
                                }
                            </div>
                        )}
                    </div>
                    <div className="rating-text">
                        <div>{ratingSurveyQuestion.lowerBoundLabel}</div>
                        <div>{ratingSurveyQuestion.upperBoundLabel}</div>
                    </div>
                    <div className="footer-branding">powered by {posthogLogoSVG} PostHog</div>
                </div>
            </div>
        </form>
    )
}
