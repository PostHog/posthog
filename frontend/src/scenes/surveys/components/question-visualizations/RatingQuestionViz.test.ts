import { NPS_DETRACTOR_VALUES, NPS_PROMOTER_VALUES } from 'scenes/surveys/constants'

import { createNPSTrendSeries, createSingleRatingTrendSeries } from './util'

describe('rating trend series', () => {
    // Survey responses are read with getSurveyResponse (JSONExtractString -> String), so every
    // comparison value must be quoted. Unquoted numeric literals make ClickHouse infer Float64 and
    // fail with "There is no supertype for types String, Float64" (CHQueryErrorNoCommonType).
    it('quotes NPS promoter values so they compare as strings', () => {
        const series = createNPSTrendSeries(NPS_PROMOTER_VALUES, 'Promoters', 0, 'q1')

        expect(series.properties[0].key).toBe("getSurveyResponse(0, 'q1') in ('9','10')")
    })

    it('quotes NPS detractor values so they compare as strings', () => {
        const series = createNPSTrendSeries(NPS_DETRACTOR_VALUES, 'Detractors', 0, 'q1')

        expect(series.properties[0].key).toBe("getSurveyResponse(0, 'q1') in ('0','1','2','3','4','5','6')")
    })

    it('omits the question id argument when not provided', () => {
        const series = createNPSTrendSeries(['9', '10'], 'Promoters', 2)

        expect(series.properties[0].key).toBe("getSurveyResponse(2, ) in ('9','10')")
    })

    it('quotes the single rating value so it compares as a string', () => {
        const series = createSingleRatingTrendSeries('2', 0, 'q1')

        expect(series.properties[0].key).toBe("getSurveyResponse(0, 'q1') = '2'")
    })
})
