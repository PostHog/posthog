// These tests deliberately cross the toolbar/product boundary, which the toolbar's own code may not. They read a save
// link back with the app's prefill parser, and they check that the toolbar's endpoint types still match the generated
// ones, so the toolbar and the user journeys product can't drift apart.
import { combineUrl } from 'kea-router'

// eslint-disable-next-line no-restricted-imports -- test only, never bundled; checks the generated types
import type {
    ElementPathsResultApi,
    JourneyStepApi,
    UserJourneysElementPathsRetrieveParams,
} from 'products/user_journeys/frontend/generated/api.schemas'
// eslint-disable-next-line no-restricted-imports -- test only, never bundled; reads the link like the app does
import { parseJourneyPrefill } from 'products/user_journeys/frontend/journeySteps'

import { elementPathsDateRange, saveAsJourneyPath } from './elementPaths'
import type { ElementPath, ElementPathsParams, ElementPathsResult, JourneyStep } from './elementPathsApiTypes'

type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false

describe('element paths', () => {
    it('declares the endpoint types the way the backend generates them', () => {
        // The check runs in `tsc`: a serializer change that makes the two sets of types disagree fails to compile here.
        const typesMatch: [
            Same<ElementPathsResult, ElementPathsResultApi>,
            Same<JourneyStep, JourneyStepApi>,
            Same<ElementPathsParams, UserJourneysElementPathsRetrieveParams>,
        ] = [true, true, true]
        expect(typesMatch).toEqual([true, true, true])
    })

    it('builds a create-form link that the app reads back into the same steps', () => {
        const path: ElementPath = {
            session_count: 3,
            share_of_anchor_sessions: 0.5,
            anchor_index: 1,
            nodes: [
                {
                    label: '/cart?step=1&x=50%',
                    is_anchor: false,
                    step_is_exact: false,
                    step: {
                        type: 'pageview',
                        url: '^https://shop\\.example\\.com/cart/*(?:[?#].*)?$',
                        url_matching: 'regex',
                    },
                },
                {
                    label: 'Pay #now & "save" 50%',
                    is_anchor: true,
                    step_is_exact: true,
                    step: {
                        type: 'element_click',
                        selector: 'button[data-attr="pay#now"] > span:nth-child(2)',
                        text: 'Pay #now & "save" 50%',
                        href: '/checkout?coupon=a+b&ref=%2F',
                        url: null,
                        url_matching: 'exact',
                    },
                },
            ],
        }

        const link = saveAsJourneyPath(path)
        expect(link.startsWith('/user-journeys/new?')).toBe(true)
        const prefill = parseJourneyPrefill(combineUrl(link).searchParams)

        expect(prefill).toMatchObject({
            stepsSkipped: false,
            draft: {
                name: 'Path through Pay #now & "save" 50%',
                source: 'toolbar',
                steps: [
                    {
                        type: 'pageview',
                        url: '^https://shop\\.example\\.com/cart/*(?:[?#].*)?$',
                        url_matching: 'regex',
                    },
                    {
                        type: 'element_click',
                        selector: 'button[data-attr="pay#now"] > span:nth-child(2)',
                        text: 'Pay #now & "save" 50%',
                        href: '/checkout?coupon=a+b&ref=%2F',
                        url_matching: 'exact',
                    },
                ],
            },
        })
    })

    it.each([
        [{ date_from: '-7d' }, '-7d', 'in the last 7 days'],
        [{ date_from: '-24h' }, '-24h', 'in the last 24 hours'],
        [{ date_from: 'dStart' }, 'dStart', 'today'],
        [{ date_from: '-31d' }, '-31d', 'in the last 31 days'],
        // The endpoint refuses more than 31 days, so a longer heatmap range falls back.
        [{ date_from: '-90d' }, '-30d', 'in the last 30 days'],
        [{ date_from: 'all' }, '-30d', 'in the last 30 days'],
        [{ date_from: '-7d', date_to: '-1d' }, '-30d', 'in the last 30 days'],
    ])('reads the heatmap range %j as %s', (filters, dateFrom, label) => {
        expect(elementPathsDateRange(filters)).toEqual({ dateFrom, label })
    })
})
