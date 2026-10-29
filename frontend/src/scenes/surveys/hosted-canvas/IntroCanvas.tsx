import { useActions, useValues } from 'kea'

import { getIntroScreenDescriptionContentType } from 'scenes/surveys/surveyIntroScreen'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { sanitizeHTML } from 'scenes/surveys/utils'

import { type Survey } from '~/types'

import { type NewSurvey } from '../constants'
import { InlineEditable } from './InlineEditable'

export function IntroCanvas({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    const { survey: baseSurvey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const appearance = survey.appearance ?? {}

    const updateAppearance = (patch: Partial<NonNullable<(Survey | NewSurvey)['appearance']>>): void => {
        setSurveyValue('appearance', { ...baseSurvey.appearance, ...patch })
    }

    return (
        <div className="intro-screen">
            <InlineEditable
                as="h1"
                className="intro-screen-header"
                value={appearance.introScreenHeader || ''}
                onChange={(value) => updateAppearance({ introScreenHeader: value })}
                placeholder="Help us improve"
                ariaLabel="Intro header"
            />
            {getIntroScreenDescriptionContentType(appearance) === 'html' && appearance.introScreenDescription ? (
                // HTML descriptions keep their rendered form; v1 doesn't inline-edit raw HTML.
                <div
                    className="intro-screen-body"
                    dangerouslySetInnerHTML={{ __html: sanitizeHTML(appearance.introScreenDescription) }}
                />
            ) : (
                <InlineEditable
                    as="p"
                    className="intro-screen-body"
                    value={appearance.introScreenDescription || ''}
                    onChange={(value) =>
                        updateAppearance({
                            introScreenDescription: value,
                            introScreenDescriptionContentType: 'text',
                        })
                    }
                    placeholder="Add an opening message (optional)"
                    ariaLabel="Intro description"
                    multiline
                />
            )}
            <div className="bottom-section">
                <InlineEditable
                    value={appearance.introScreenButtonText || ''}
                    onChange={(value) => updateAppearance({ introScreenButtonText: value })}
                    placeholder="Get started"
                    ariaLabel="Intro button label"
                    className="form-submit"
                />
            </div>
        </div>
    )
}
