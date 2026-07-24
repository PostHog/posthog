import { SurveyPosition, SurveyWidgetType } from '~/types'

import { resolveWidgetPosition } from './constants'

describe('resolveWidgetPosition', () => {
    test.each([
        [SurveyWidgetType.Tab, SurveyPosition.NextToTrigger, SurveyPosition.Right],
        [SurveyWidgetType.Button, SurveyPosition.NextToTrigger, SurveyPosition.Right],
        [SurveyWidgetType.Selector, SurveyPosition.NextToTrigger, SurveyPosition.NextToTrigger],
        [SurveyWidgetType.Tab, SurveyPosition.Left, SurveyPosition.Left],
        [SurveyWidgetType.Selector, undefined, undefined],
    ])('widgetType=%s currentPosition=%s -> %s', (widgetType, currentPosition, expected) => {
        expect(resolveWidgetPosition(widgetType, currentPosition)).toBe(expected)
    })
})
