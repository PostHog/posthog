import './SurveyAppearance.scss'
import { LemonInput } from '@posthog/lemon-ui'
import { useState } from 'react'
import { SurveyAppearance as SurveyAppearanceType } from '~/types'

interface SurveyAppearanceProps {
    // type: string
    question: string
    appearance: SurveyAppearanceType
    readOnly?: boolean
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
}
export function SurveyAppearance({
    question,
    appearance,
    readOnly,
    onAppearanceChange,
}: SurveyAppearanceProps): JSX.Element {
    return (
        <>
            <h3 className="mb-4 text-center">Preview</h3>
            <BaseAppearance question={question} appearance={appearance} />
            {!readOnly && (
                <div className="flex flex-col">
                    <div className="mt-2">Background color</div>
                    <LemonInput
                        value={appearance?.backgroundColor}
                        onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    />
                    <div className="mt-2">Text color</div>
                    <LemonInput
                        value={appearance?.textColor}
                        onChange={(textColor) => onAppearanceChange({ ...appearance, textColor })}
                    />
                    <div className="mt-2">Submit button color</div>
                    <LemonInput
                        value={appearance?.submitButtonColor}
                        onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                    />
                </div>
            )}
        </>
    )
}
const posthogLogoSVG = (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="12" viewBox="0 0 50 30" fill="none">
        <path
            d="M10.8914 17.2057c-.3685.7371-1.42031.7371-1.78884 0L8.2212 15.443c-.14077-.2815-.14077-.6129 0-.8944l.88136-1.7627c.36853-.7371 1.42034-.7371 1.78884 0l.8814 1.7627c.1407.2815.1407.6129 0 .8944l-.8814 1.7627zM10.8914 27.2028c-.3685.737-1.42031.737-1.78884 0L8.2212 25.44c-.14077-.2815-.14077-.6129 0-.8944l.88136-1.7627c.36853-.7371 1.42034-.7371 1.78884 0l.8814 1.7627c.1407.2815.1407.6129 0 .8944l-.8814 1.7628z"
            fill="##6A6B69"
        />
        <path
            d="M0 23.4082c0-.8909 1.07714-1.3371 1.70711-.7071l4.58338 4.5834c.62997.63.1838 1.7071-.7071 1.7071H.999999c-.552284 0-.999999-.4477-.999999-1v-4.5834zm0-4.8278c0 .2652.105357.5196.292893.7071l9.411217 9.4112c.18753.1875.44189.2929.70709.2929h5.1692c.8909 0 1.3371-1.0771.7071-1.7071L1.70711 12.7041C1.07714 12.0741 0 12.5203 0 13.4112v5.1692zm0-9.99701c0 .26521.105357.51957.292893.7071L19.7011 28.6987c.1875.1875.4419.2929.7071.2929h5.1692c.8909 0 1.3371-1.0771.7071-1.7071L1.70711 2.70711C1.07715 2.07715 0 2.52331 0 3.41421v5.16918zm9.997 0c0 .26521.1054.51957.2929.7071l17.994 17.99401c.63.63 1.7071.1838 1.7071-.7071v-5.1692c0-.2652-.1054-.5196-.2929-.7071l-17.994-17.994c-.63-.62996-1.7071-.18379-1.7071.70711v5.16918zm11.7041-5.87628c-.63-.62997-1.7071-.1838-1.7071.7071v5.16918c0 .26521.1054.51957.2929.7071l7.997 7.99701c.63.63 1.7071.1838 1.7071-.7071v-5.1692c0-.2652-.1054-.5196-.2929-.7071l-7.997-7.99699z"
            fill="#6A6B69"
        />
        <path
            d="M42.5248 23.5308l-9.4127-9.4127c-.63-.63-1.7071-.1838-1.7071.7071v13.1664c0 .5523.4477 1 1 1h14.5806c.5523 0 1-.4477 1-1v-1.199c0-.5523-.4496-.9934-.9973-1.0647-1.6807-.2188-3.2528-.9864-4.4635-2.1971zm-6.3213 2.2618c-.8829 0-1.5995-.7166-1.5995-1.5996 0-.8829.7166-1.5995 1.5995-1.5995.883 0 1.5996.7166 1.5996 1.5995 0 .883-.7166 1.5996-1.5996 1.5996z"
            fill="#6A6B69"
        />
        <path
            d="M0 27.9916c0 .5523.447715 1 1 1h4.58339c.8909 0 1.33707-1.0771.70711-1.7071l-4.58339-4.5834C1.07714 22.0711 0 22.5173 0 23.4082v4.5834zM9.997 10.997L1.70711 2.70711C1.07714 2.07714 0 2.52331 0 3.41421v5.16918c0 .26521.105357.51957.292893.7071L9.997 18.9946V10.997zM1.70711 12.7041C1.07714 12.0741 0 12.5203 0 13.4112v5.1692c0 .2652.105357.5196.292893.7071L9.997 28.9916V20.994l-8.28989-8.2899z"
            fill="#6A6B69"
        />
        <path
            d="M19.994 11.4112c0-.2652-.1053-.5196-.2929-.7071l-7.997-7.99699c-.6299-.62997-1.70709-.1838-1.70709.7071v5.16918c0 .26521.10539.51957.29289.7071l9.7041 9.70411v-7.5834zM9.99701 28.9916h5.58339c.8909 0 1.3371-1.0771.7071-1.7071L9.99701 20.994v7.9976zM9.99701 10.997v7.5834c0 .2652.10539.5196.29289.7071l9.7041 9.7041v-7.5834c0-.2652-.1053-.5196-.2929-.7071L9.99701 10.997z"
            fill="#6a6b69"
        />
    </svg>
)
// This should be synced to the UI of the surveys app plugin
function BaseAppearance({ question, appearance }: { question: string; appearance: SurveyAppearanceType }): JSX.Element {
    const [hasText, setHasText] = useState(false)

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
                    <textarea
                        className="survey-textarea"
                        name="survey"
                        rows={4}
                        onChange={(event) => setHasText(!!event?.target.value)}
                    />
                </div>
                <div className="bottom-section">
                    <div className="buttons">
                        <button
                            className="form-submit"
                            type="button"
                            disabled={!hasText}
                            onClick={() => {}}
                            style={{ backgroundColor: appearance.submitButtonColor }}
                        >
                            Submit
                        </button>
                    </div>
                    <div className="footer-branding">powered by {posthogLogoSVG} PostHog</div>
                </div>
            </div>
        </form>
    )
}
